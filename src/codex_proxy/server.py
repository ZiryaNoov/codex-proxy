"""FastAPI server — WebSocket + HTTP endpoints for Codex CLI.

v5.0.0: Added database integration, multi-provider support, and request logging.
Maintains full v4 backward compatibility when no v5 config sections are enabled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .circuit_breaker import CircuitBreaker
from .config import ProxyConfig
from .key_rotation import KeyRotator, _mask_key
from .plugins import PluginContext, PluginRegistry
from .providers import ProviderAdapter, get_adapter
from .rate_limiter import RateLimiter
from .store import ResponseStore
from .translator import (
    accumulate_tool_call,
    build_cc_request,
    build_final_output,
    cc_to_response,
    generate_response_id,
    parse_cc_stream,
    stream_cc_to_response,
    unwrap_envelope,
)

logger = logging.getLogger("codex-proxy")


# ── Multi-provider state ─────────────────────────────────────────────────

@dataclass
class ProviderState:
    """Runtime state for a single provider."""
    config: Any  # ProviderConfig
    adapter: ProviderAdapter
    base_url: str
    client: httpx.AsyncClient
    key_rotator: KeyRotator | None = None


@dataclass
class AppState:
    config: ProxyConfig
    store: ResponseStore
    client: httpx.AsyncClient  # primary client (v4 compat)
    adapter: ProviderAdapter   # primary adapter (v4 compat)
    circuit_breaker: CircuitBreaker | None
    start_time: float = 0.0
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_request_time: float = 0.0
    key_rotator: KeyRotator | None = None
    plugin_registry: PluginRegistry | None = None
    rate_limiter: RateLimiter | None = None
    # v5 additions — None when v5 features are disabled
    db_engine: Any | None = None       # sqlalchemy AsyncEngine
    db_session_factory: Any | None = None  # async_sessionmaker
    providers_map: dict[str, ProviderState] = field(default_factory=dict)
    smart_router: Any | None = None    # SmartRouter when routing enabled


@asynccontextmanager
async def lifespan(app):
    state: AppState = app.state.proxy
    if state.plugin_registry:
        await state.plugin_registry.on_startup(state.config)
    yield
    if state.plugin_registry:
        await state.plugin_registry.on_shutdown()
    if state.client:
        await state.client.aclose()
    # Close provider clients
    for ps in state.providers_map.values():
        await ps.client.aclose()
    # Close database
    if state.db_engine:
        from .db import close_db
        await close_db(state.db_engine)
    logger.info("codex-proxy shut down")


app = FastAPI(title="codex-proxy", lifespan=lifespan)


def configure(config: ProxyConfig) -> None:
    """Configure the proxy. Sync — sets up state on app.

    In v5 mode (database enabled), call configure_async() instead
    for full async initialization including DB setup.
    """
    store = ResponseStore(
        ttl_seconds=config.store.ttl_seconds,
        max_entries=config.store.max_entries,
    )
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=config.server.connect_timeout,
            read=config.server.read_timeout,
            write=10, pool=30,
        ),
    )
    adapter = get_adapter(config.provider.name)
    cb_config = config.circuit_breaker
    cb = CircuitBreaker(
        failure_threshold=cb_config.failure_threshold,
        recovery_timeout=cb_config.recovery_timeout,
    ) if cb_config.enabled else None
    keys = config.provider.effective_api_keys()
    key_rotator = None
    if len(keys) > 1:
        key_rotator = KeyRotator(
            keys=keys,
            failure_threshold=cb_config.failure_threshold,
            recovery_timeout=cb_config.recovery_timeout,
        )
    rl_config = config.rate_limit
    rate_limiter = RateLimiter(
        max_requests=rl_config.max_requests,
        window_seconds=rl_config.window_seconds,
    ) if rl_config.enabled else None

    # Build multi-provider map
    providers_map = _build_providers_map(config, client)

    app.state.proxy = AppState(
        config=config, store=store, client=client,
        adapter=adapter, circuit_breaker=cb, start_time=time.time(),
        key_rotator=key_rotator,
        plugin_registry=_build_plugin_registry(config),
        rate_limiter=rate_limiter,
        providers_map=providers_map,
    )
    # CORS middleware (add only if origins configured)
    if config.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.server.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )


async def configure_async(config: ProxyConfig) -> None:
    """Async configure — includes database initialization for v5 mode."""
    # Run sync config first
    configure(config)

    if not config.is_v5_mode:
        return

    state = _state()

    # Initialize database if enabled
    if config.database.enabled:
        from .db import init_db
        engine, session_factory = await init_db(config.effective_db_url)
        state.db_engine = engine
        state.db_session_factory = session_factory
        logger.info("v5 database enabled: %s", config.effective_db_url.split(":///")[-1])

        # Seed providers from config into DB
        await _seed_providers_from_config(state)

    # Initialize auth if enabled (requires database)
    if config.auth.enabled:
        if not state.db_session_factory:
            logger.error("Auth requires database to be enabled. Disabling auth.")
            config.auth.enabled = False
        else:
            from .auth import ensure_secret_key, seed_admin_user
            ensure_secret_key(config)
            await seed_admin_user(state.db_session_factory, config)
            logger.info("v5 auth enabled — admin: %s", config.auth.admin_username)

    # Initialize smart router if enabled
    if config.router.enabled:
        from .router import SmartRouter
        state.smart_router = SmartRouter(
            strategy=config.router.default_strategy,
            providers_map=state.providers_map,
        )
        logger.info("v5 router enabled — strategy: %s", config.router.default_strategy)

    logger.info("v5 mode active — features: database=%s auth=%s router=%s dashboard=%s",
                config.database.enabled, config.auth.enabled,
                config.router.enabled, config.dashboard.enabled)


async def _seed_providers_from_config(state: AppState) -> None:
    """Seed provider tables from config on first startup."""
    if not state.db_session_factory:
        return

    from .db import crud_providers
    from cryptography.fernet import Fernet

    async with state.db_session_factory() as session:
        existing = await crud_providers.list_providers(session)
        if existing:
            return  # Already seeded

        # Seed from config
        for pcfg in state.config.all_providers():
            provider = await crud_providers.create_provider(
                session,
                name=pcfg.name,
                display_name=pcfg.display_name,
                base_url=pcfg.base_url,
                adapter_name=pcfg.name,
                extra_headers=pcfg.extra_headers,
            )

            # Store API keys (encrypted with a simple key for now)
            keys = pcfg.effective_api_keys()
            if keys:
                # Generate a Fernet key for encryption (stored per-instance)
                fernet_key = Fernet.generate_key()
                fernet = Fernet(fernet_key)
                for key in keys:
                    encrypted = fernet.encrypt(key.encode()).decode()
                    prefix = key[:8] if len(key) >= 8 else key
                    await crud_providers.add_provider_key(
                        session,
                        provider_id=provider["id"],
                        encrypted_key=encrypted,
                        key_prefix=prefix,
                    )
            logger.info("Seeded provider: %s (%d keys)", pcfg.name, len(keys))


def _build_providers_map(config: ProxyConfig, primary_client: httpx.AsyncClient) -> dict[str, ProviderState]:
    """Build the multi-provider map from config."""
    providers_map: dict[str, ProviderState] = {}

    for pcfg in config.all_providers():
        client = primary_client  # Share the primary client for now
        adapter = get_adapter(pcfg.name)
        keys = pcfg.effective_api_keys()
        key_rotator = None
        if len(keys) > 1:
            cb_config = config.circuit_breaker
            key_rotator = KeyRotator(
                keys=keys,
                failure_threshold=cb_config.failure_threshold,
                recovery_timeout=cb_config.recovery_timeout,
            )

        providers_map[pcfg.name] = ProviderState(
            config=pcfg,
            adapter=adapter,
            base_url=pcfg.base_url,
            client=client,
            key_rotator=key_rotator,
        )

    return providers_map


def _resolve_provider(state: AppState, model: str) -> tuple[ProviderState, str]:
    """Resolve which provider to use for a given model.

    Uses the SmartRouter when enabled, otherwise falls back to
    simple model-to-provider matching.
    """
    # Use smart router if enabled
    if state.smart_router and state.config.router.enabled:
        provider_name, _ = state.smart_router.select_provider(
            model, state.providers_map, state.db_session_factory)
        if provider_name in state.providers_map:
            return state.providers_map[provider_name], model

    # Try to find a provider that has this model
    for name, ps in state.providers_map.items():
        if model in ps.config.models:
            return ps, model

    # If only one provider, use it regardless
    if len(state.providers_map) == 1:
        ps = next(iter(state.providers_map.values()))
        return ps, model

    # Fallback to primary provider
    return state.providers_map.get(
        state.config.provider.name,
        next(iter(state.providers_map.values())),
    ), model


def _state() -> AppState:
    val = app.state.proxy
    assert isinstance(val, AppState)
    return val


def _require_admin(authorization: str = Header(default="")) -> None:
    """Dependency that enforces admin token on protected endpoints."""
    state = _state()
    token = state.config.server.admin_token
    if token and authorization != f"Bearer {token}":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin token required")


def _client_id(request: Request) -> str:
    """Extract a client identifier for rate limiting."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _build_plugin_registry(config: ProxyConfig) -> PluginRegistry | None:
    if config.plugins.enabled and config.plugins.plugins:
        registry = PluginRegistry()
        registry.load(config.plugins.plugins)
        return registry
    return None


def _build_plugin_ctx(request_id: str, method: str, model: str,
                      api_key: str, stream: bool) -> PluginContext:
    state = _state()
    return PluginContext(
        request_id=request_id, method=method, model=model,
        provider=state.config.provider.name,
        api_key_masked=_mask_key(api_key), stream=stream,
    )


def _api_key(auth_header: str) -> str:
    if auth_header:
        lower = auth_header.lower()
        if lower.startswith("bearer "):
            return auth_header[7:].strip()
        return auth_header.strip()
    state = _state()
    if state.key_rotator:
        return state.key_rotator.next_key()
    return state.config.provider.effective_api_key()


def _cc_headers(api_key: str, adapter: ProviderAdapter | None = None) -> dict:
    state = _state()
    a = adapter or state.adapter
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # Merge extra_headers from resolved provider config
    h.update(state.config.provider.extra_headers)
    return a.adjust_headers(h)


def _backend_url() -> str:
    return _state().config.provider.base_url


async def _post_with_retry(url: str, json_body: dict, headers: dict,
                           client: httpx.AsyncClient | None = None) -> httpx.Response:
    """POST with retry on 5xx or transport errors."""
    state = _state()
    max_retries = state.config.server.max_retries
    retry_delay = state.config.server.retry_delay
    c = client or state.client
    for attempt in range(max_retries + 1):
        try:
            r = await c.post(url, json=json_body, headers=headers)
            if r.status_code < 500 or attempt == max_retries:
                return r
            logger.warning("Upstream 5xx (attempt %d), retrying...", attempt + 1)
        except httpx.TransportError as e:
            if attempt == max_retries:
                raise
            logger.warning("Transport error (attempt %d): %s, retrying...", attempt + 1, e)
        await asyncio.sleep(retry_delay)
    raise httpx.TransportError("Max retries exceeded")


async def _request_with_key_failover(url: str, json_body: dict,
                                     headers: dict, api_key: str,
                                     key_rotator: KeyRotator | None = None,
                                     client: httpx.AsyncClient | None = None) -> httpx.Response:
    """POST with retry. On auth/rate-limit errors, rotate key and retry."""
    state = _state()
    kr = key_rotator or state.key_rotator
    if not kr:
        return await _post_with_retry(url, json_body, headers, client)
    max_attempts = kr.key_count
    r: httpx.Response | None = None
    for _ in range(max_attempts):
        r = await _post_with_retry(url, json_body, headers, client)
        if r.status_code in (401, 403, 429):
            kr.record_failure(api_key, r.status_code)
            api_key = kr.next_key()
            headers = _cc_headers(api_key)
            logger.warning("Key failed with %d, rotating", r.status_code)
            continue
        if r.status_code < 400:
            kr.record_success(api_key)
        return r
    assert r is not None
    return r


async def _log_request(state: AppState, request_id: str, model: str,
                       method: str, provider_name: str,
                       input_tokens: int, output_tokens: int,
                       cost_usd: float, latency_ms: float,
                       status_code: int | None, error: str | None,
                       is_stream: bool, user_id: str | None = None) -> None:
    """Log a request to the database (non-blocking, best-effort).

    Calculates real cost from model pricing when possible.
    Records latency in the smart router for adaptive routing.
    """
    # Record latency for smart router
    if state.smart_router and provider_name:
        success = status_code is None or status_code < 400
        state.smart_router.record_latency(provider_name, latency_ms, success)

    if not state.db_session_factory:
        return

    # Calculate real cost if not provided
    actual_cost = cost_usd
    if actual_cost == 0.0 and (input_tokens > 0 or output_tokens > 0):
        try:
            from .cost import calculate_cost
            actual_cost = await calculate_cost(
                model, input_tokens, output_tokens, state.db_session_factory)
        except Exception:
            pass

    try:
        from .db import crud_logs, crud_providers
        async with state.db_session_factory() as session:
            # Resolve provider_id from provider_name
            provider_id = None
            try:
                p = await crud_providers.get_provider_by_name(session, provider_name)
                if p:
                    provider_id = p["id"]
            except Exception:
                pass

            await crud_logs.insert_log(
                session,
                user_id=user_id,
                provider_id=provider_id,
                request_id=request_id,
                model=model,
                method=method,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_usd=actual_cost,
                latency_ms=latency_ms,
                status_code=status_code,
                error_message=error,
                is_stream=is_stream,
            )
            await session.commit()
    except Exception as e:
        logger.warning("Failed to log request: %s", e)


# ── HTTP endpoint ───────────────────────────────────────────────────────

@app.post("/responses")
async def responses_http(request: Request,
                         authorization: str = Header(default="")):
    state = _state()

    # Rate limiting
    if state.rate_limiter:
        cid = _client_id(request)
        if not state.rate_limiter.allow(cid):
            return JSONResponse(
                {"error": {"message": "Rate limit exceeded", "code": "rate_limited"}},
                status_code=429,
            )

    # Request size check
    content_length = request.headers.get("content-length", "0")
    max_bytes = state.config.server.max_request_body_bytes
    if int(content_length) > max_bytes:
        return JSONResponse(
            {"error": {"message": "Request too large", "code": "request_too_large"}},
            status_code=413,
        )

    state.request_count += 1
    state.last_request_time = time.time()

    if state.circuit_breaker and not state.circuit_breaker.can_execute():
        return JSONResponse(
            {"error": {"message": "Circuit breaker open", "code": "circuit_open"}},
            status_code=503,
        )

    body = await request.json()
    body = state.store.resolve_input(body)
    model = body.get("model", state.config.provider.default_model)
    stream = body.get("stream", False)

    # Resolve provider (multi-provider support)
    ps, resolved_model = _resolve_provider(state, model)
    adapter = ps.adapter
    base_url = ps.base_url
    key_rotator = ps.key_rotator or state.key_rotator

    api_key = _api_key(authorization)

    cc_body = build_cc_request(
        body,
        compaction_enabled=state.config.compaction.enabled,
        compaction_max_messages=state.config.compaction.max_messages,
        compaction_keep_last=state.config.compaction.keep_last,
    )
    cc_body["model"] = resolved_model
    cc_body["stream"] = stream
    cc_body = adapter.adjust_request(cc_body)
    headers = _cc_headers(api_key, adapter)

    # Plugin: on_request
    req_id = uuid.uuid4().hex[:12]
    if state.plugin_registry:
        ctx = _build_plugin_ctx(req_id, "http", model, api_key, stream)
        await state.plugin_registry.on_request(ctx)

    start_t = time.monotonic()

    if stream:
        result_holder: dict = {}
        original_input = body.get("input", [])

        async def _stream():
            async with ps.client.stream("POST", f"{base_url}/chat/completions",
                                        json=cc_body, headers=headers) as resp:
                if resp.status_code >= 400:
                    error_body = await resp.aread()
                    logger.error("Upstream error %d: %s", resp.status_code, error_body[:500])
                    if state.circuit_breaker:
                        state.circuit_breaker.record_failure()
                    state.failure_count += 1
                    duration = (time.monotonic() - start_t) * 1000
                    await _log_request(state, req_id, model, "http", ps.config.name,
                                       0, 0, 0, duration, resp.status_code,
                                       error_body[:200].decode(errors="replace"), True)
                    yield f"event: error\ndata: {json.dumps({'error': {'message': 'upstream error', 'status': resp.status_code}})}\n\n"
                    return

                if state.circuit_breaker:
                    state.circuit_breaker.record_success()
                state.success_count += 1

                gen = stream_cc_to_response(resp.aiter_lines(), model, result=result_holder)
                async for chunk in gen:
                    yield chunk

            completed = result_holder.get("response")
            if completed:
                state.store.put(completed["id"], {**completed, "_original_input": original_input})

            # Log to DB
            duration = (time.monotonic() - start_t) * 1000
            resp_data = result_holder.get("response", {})
            usage = resp_data.get("usage", {})
            await _log_request(state, req_id, model, "http", ps.config.name,
                               usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                               0.0, duration, 200, None, True)

        return StreamingResponse(_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    r = await _request_with_key_failover(
        f"{base_url}/chat/completions", cc_body, headers, api_key,
        key_rotator=key_rotator, client=ps.client)
    duration = (time.monotonic() - start_t) * 1000

    if r.status_code >= 400:
        logger.error("Upstream error %d: %s", r.status_code, r.text[:500])
        if state.circuit_breaker:
            state.circuit_breaker.record_failure()
        state.failure_count += 1
        if state.plugin_registry:
            ectx = _build_plugin_ctx(req_id, "http", model, api_key, stream)
            ectx.status_code = r.status_code
            ectx.error = r.text[:200]
            ectx.duration_ms = duration
            await state.plugin_registry.on_error(ectx)
        await _log_request(state, req_id, model, "http", ps.config.name,
                           0, 0, 0, duration, r.status_code, r.text[:200], False)
        return JSONResponse({"error": {"message": "upstream error",
                                       "status": r.status_code}},
                            status_code=502)

    if state.circuit_breaker:
        state.circuit_breaker.record_success()
    state.success_count += 1
    if state.plugin_registry:
        rctx = _build_plugin_ctx(req_id, "http", model, api_key, stream)
        rctx.status_code = r.status_code
        rctx.duration_ms = duration
        await state.plugin_registry.on_response(rctx)
    resp = cc_to_response(r.json(), model)
    state.store.put(resp["id"], {**resp, "_original_input": body.get("input", [])})

    # Log to DB with usage data
    usage = resp.get("usage", {})
    await _log_request(state, req_id, model, "http", ps.config.name,
                       usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                       0.0, duration, 200, None, False)

    return JSONResponse(resp)


# ── WebSocket endpoint ──────────────────────────────────────────────────

@app.websocket("/responses")
async def responses_ws(ws: WebSocket):
    state = _state()

    await ws.accept()
    api_key = ""
    auth = ws.headers.get("authorization", "")
    if auth:
        api_key = _api_key(auth)
    if not api_key:
        if state.key_rotator:
            api_key = state.key_rotator.next_key()
        else:
            api_key = state.config.provider.effective_api_key()

    try:
        while True:
            raw = await ws.receive_text()
            try:
                body = unwrap_envelope(raw)
            except json.JSONDecodeError:
                continue

            state.request_count += 1
            state.last_request_time = time.time()
            # Rotate key per message when no client auth header
            if not auth and state.key_rotator:
                api_key = state.key_rotator.next_key()
            body = state.store.resolve_input(body)
            model = body.get("model", state.config.provider.default_model)

            # Resolve provider
            ps, resolved_model = _resolve_provider(state, model)

            cc_body = build_cc_request(
                body,
                compaction_enabled=state.config.compaction.enabled,
                compaction_max_messages=state.config.compaction.max_messages,
                compaction_keep_last=state.config.compaction.keep_last,
            )
            cc_body["model"] = resolved_model
            cc_body["stream"] = True
            cc_body = ps.adapter.adjust_request(cc_body)
            headers = _cc_headers(api_key, ps.adapter)

            if state.circuit_breaker and not state.circuit_breaker.can_execute():
                error_resp = {
                    "id": generate_response_id(), "object": "response",
                    "created_at": int(time.time()), "model": model,
                    "status": "failed", "output": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0,
                              "total_tokens": 0},
                    "error": {"message": "Circuit breaker open",
                              "code": "circuit_open"},
                }
                await ws.send_text(json.dumps(
                    {"type": "response.failed", "response": error_resp}))
                continue

            rid = generate_response_id()
            mid = f"msg_{uuid.uuid4().hex[:24]}"
            now = int(time.time())
            start_t = time.monotonic()

            init = {"id": rid, "object": "response", "created_at": now,
                    "model": model, "status": "in_progress", "output": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0,
                              "total_tokens": 0}}

            await ws.send_text(json.dumps(
                {"type": "response.created", "response": init}))
            await ws.send_text(json.dumps(
                {"type": "response.in_progress", "response": init}))
            await ws.send_text(json.dumps({
                "type": "response.output_item.added", "output_index": 0,
                "item": {"type": "message", "id": mid,
                         "status": "in_progress", "role": "assistant",
                         "content": []}}))
            await ws.send_text(json.dumps({
                "type": "response.content_part.added", "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": "",
                         "annotations": []}}))

            full_text = ""
            reasoning_text = ""
            tool_calls: list[dict] = []
            usage_data = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

            try:
                async with ps.client.stream(
                    "POST", f"{ps.base_url}/chat/completions",
                    json=cc_body, headers=headers
                ) as resp:
                    async for event_type, data in parse_cc_stream(resp.aiter_lines()):
                        if event_type == "reasoning":
                            reasoning_text += data
                        elif event_type == "text":
                            full_text += data
                            await ws.send_text(json.dumps({
                                "type": "response.output_text.delta",
                                "output_index": 0,
                                "content_index": 0, "delta": data}))
                        elif event_type == "tool_call":
                            accumulate_tool_call(tool_calls, data)
                        elif event_type == "usage":
                            usage_data = {
                                "input_tokens": data.get("prompt_tokens", 0),
                                "output_tokens": data.get("completion_tokens", 0),
                                "total_tokens": data.get("total_tokens", 0),
                            }
            except Exception as e:
                logger.error("WS upstream error: %s", e)
                if state.circuit_breaker:
                    state.circuit_breaker.record_failure()
                state.failure_count += 1
                duration = (time.monotonic() - start_t) * 1000
                await _log_request(state, rid[:12], model, "ws", ps.config.name,
                                   0, 0, 0, duration, None, str(e)[:200], True)
                error_resp = {
                    "id": rid, "object": "response", "created_at": now,
                    "model": model, "status": "failed",
                    "output": [], "usage": {"input_tokens": 0,
                                            "output_tokens": 0,
                                            "total_tokens": 0},
                    "error": {"message": f"Upstream error: {e}",
                              "code": "upstream_error"},
                }
                await ws.send_text(json.dumps(
                    {"type": "response.failed", "response": error_resp}))
                continue

            # Finish text
            if state.circuit_breaker:
                state.circuit_breaker.record_success()
            state.success_count += 1
            await ws.send_text(json.dumps({
                "type": "response.output_text.done", "output_index": 0,
                "content_index": 0, "text": full_text}))
            await ws.send_text(json.dumps({
                "type": "response.content_part.done", "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": full_text,
                         "annotations": []}}))
            await ws.send_text(json.dumps({
                "type": "response.output_item.done", "output_index": 0,
                "item": {"type": "message", "id": mid,
                         "status": "completed", "role": "assistant",
                         "content": [{"type": "output_text",
                                      "text": full_text,
                                      "annotations": []}]}}))

            # Build final output using shared function
            final_out = build_final_output(mid, full_text, reasoning_text, tool_calls)

            # Emit tool call events
            text_and_reasoning_count = len(final_out) - len(tool_calls)
            for i, item in enumerate(final_out[text_and_reasoning_count:], text_and_reasoning_count):
                fc = {k: v for k, v in item.items() if k != "status"}
                await ws.send_text(json.dumps({
                    "type": "response.output_item.added",
                    "output_index": i, "item": fc}))
                await ws.send_text(json.dumps({
                    "type": "response.output_item.done",
                    "output_index": i, "item": fc}))

            completed = {"id": rid, "object": "response",
                         "created_at": now, "model": model,
                         "status": "completed", "output": final_out,
                         "usage": usage_data}
            await ws.send_text(json.dumps(
                {"type": "response.completed",
                 "response": completed}))

            state.store.put(rid, {**completed,
                                  "_original_input": body.get("input", [])})

            # Log to DB
            duration = (time.monotonic() - start_t) * 1000
            await _log_request(state, rid[:12], model, "ws", ps.config.name,
                               usage_data.get("input_tokens", 0),
                               usage_data.get("output_tokens", 0),
                               0.0, duration, 200, None, True)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)


# ── Utility endpoints ───────────────────────────────────────────────────

@app.get("/responses/{response_id}")
async def get_response(response_id: str):
    state = _state()
    resp = state.store.get(response_id)
    if not resp:
        return JSONResponse(
            {"error": {"message": "Response not found", "code": "not_found"}},
            status_code=404,
        )
    clean = {k: v for k, v in resp.items() if not k.startswith("_")}
    return JSONResponse(clean)


@app.get("/models")
@app.get("/v1/models")
async def models():
    state = _state()
    # Collect models from all providers
    all_models = []
    seen = set()
    for pcfg in state.config.all_providers():
        for m in pcfg.models:
            if m not in seen:
                all_models.append({"id": m, "object": "model", "owned_by": pcfg.name})
                seen.add(m)
    return JSONResponse({"object": "list", "data": all_models})


@app.get("/health")
async def health(request: Request):
    state = _state()
    result: dict[str, Any] = {
        "status": "ok",
        "proxy": "codex-proxy",
        "version": __version__,
    }
    if state.config.is_v5_mode:
        result["mode"] = "v5"
        result["features"] = {
            "database": state.config.database.enabled,
            "auth": state.config.auth.enabled,
            "router": state.config.router.enabled,
            "dashboard": state.config.dashboard.enabled,
        }
    if request.query_params.get("check_backend"):
        try:
            r = await state.client.get(
                f"{state.config.provider.base_url}/models",
                headers={"Authorization": f"Bearer {state.config.provider.effective_api_key()}"},
                timeout=5.0,
            )
            result["backend"] = "ok" if r.status_code < 400 else "error"
            result["backend_status"] = r.status_code
        except Exception as e:
            result["backend"] = "unreachable"
            result["backend_error"] = str(e)
            result["status"] = "degraded"
    return result


@app.get("/status")
async def status(authorization: str = Header(default="")):
    _require_admin(authorization)
    state = _state()
    uptime = int(time.time() - state.start_time)
    result = {
        "proxy": "codex-proxy",
        "version": __version__,
        "status": "running",
        "uptime_seconds": uptime,
        "requests_total": state.request_count,
        "response_store_size": state.store.size(),
        "provider": {
            "name": state.config.provider.name,
            "display_name": state.config.provider.display_name,
            "base_url": state.config.provider.base_url,
            "models": state.config.provider.models,
            "default_model": state.config.provider.default_model,
        },
        "server": {
            "host": state.config.server.host,
            "port": state.config.server.port,
        },
    }
    if state.config.is_v5_mode:
        result["mode"] = "v5"
        result["providers_count"] = len(state.providers_map)
        result["database"] = state.config.database.enabled
        result["auth"] = state.config.auth.enabled
        result["router"] = state.config.router.enabled
        result["dashboard"] = state.config.dashboard.enabled
    if state.smart_router:
        result["router_status"] = state.smart_router.get_status()
    if state.circuit_breaker:
        result["circuit_breaker"] = state.circuit_breaker.get_status()
    if state.key_rotator:
        result["key_rotation"] = {
            "total_keys": state.key_rotator.key_count,
            "keys": state.key_rotator.get_status(),
        }
    if state.plugin_registry:
        result["plugins"] = {
            "enabled": True,
            "loaded": state.plugin_registry.list_plugins(),
        }
    if state.rate_limiter:
        result["rate_limit"] = state.rate_limiter.get_status()
    return JSONResponse(result)


def reload_config_internal(state: AppState) -> tuple[str, str]:
    """Internal config reload — updates state in-place.

    Returns a tuple of (display_name, default_model).
    """
    from .config import load_config
    new_config = load_config()
    state.config = new_config
    state.adapter = get_adapter(new_config.provider.name)
    if (new_config.store.ttl_seconds != state.store.ttl_seconds or
            new_config.store.max_entries != state.store.max_entries):
        state.store = ResponseStore(
            ttl_seconds=new_config.store.ttl_seconds,
            max_entries=new_config.store.max_entries,
        )
    cb_config = new_config.circuit_breaker
    state.circuit_breaker = CircuitBreaker(
        failure_threshold=cb_config.failure_threshold,
        recovery_timeout=cb_config.recovery_timeout,
    ) if cb_config.enabled else None
    keys = new_config.provider.effective_api_keys()
    if len(keys) > 1:
        state.key_rotator = KeyRotator(
            keys=keys,
            failure_threshold=cb_config.failure_threshold,
            recovery_timeout=cb_config.recovery_timeout,
        )
    else:
        state.key_rotator = None
    rl_config = new_config.rate_limit
    state.rate_limiter = RateLimiter(
        max_requests=rl_config.max_requests,
        window_seconds=rl_config.window_seconds,
    ) if rl_config.enabled else None
    state.plugin_registry = _build_plugin_registry(new_config)
    # Rebuild providers map
    state.providers_map = _build_providers_map(new_config, state.client)
    return new_config.provider.display_name, new_config.provider.default_model


@app.post("/reload")
async def reload_config(authorization: str = Header(default="")):
    """Reload config from disk without restarting."""
    _require_admin(authorization)
    state = _state()
    old_registry = state.plugin_registry
    try:
        display_name, default_model = reload_config_internal(state)
        if old_registry:
            await old_registry.on_shutdown()
        if state.plugin_registry:
            await state.plugin_registry.on_startup(state.config)
        logger.info("Config reloaded successfully")
        return {"status": "reloaded", "provider": display_name,
                "model": default_model}
    except Exception as e:
        logger.error("Config reload failed: %s", e)
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500,
        )


# ── v5 Auth endpoints ────────────────────────────────────────────────────

@app.post("/auth/login")
async def auth_login(request: Request):
    """Authenticate user and return JWT tokens."""
    from fastapi import HTTPException
    from .auth import verify_password, create_access_token, create_refresh_token

    state = _state()
    if not state.config.auth.enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")

    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    # Look up user in DB
    if not state.db_session_factory:
        raise HTTPException(status_code=500, detail="Database not available")

    from .db import crud_users
    async with state.db_session_factory() as session:
        user = await crud_users.get_user_by_username(session, username)

    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token_data = {"sub": user["id"], "username": user["username"], "role": user["role"]}
    access_token = create_access_token(
        token_data, state.config.auth.secret_key,
        state.config.auth.access_token_expire_minutes)
    refresh_token = create_refresh_token(
        token_data, state.config.auth.secret_key,
        state.config.auth.refresh_token_expire_days)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": state.config.auth.access_token_expire_minutes * 60,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
    }


@app.post("/auth/signup")
async def auth_signup(request: Request):
    """Register a new user. Only admins can create users (or first user is auto-admin)."""
    from fastapi import HTTPException
    from .auth import hash_password, create_access_token, create_refresh_token, decode_token

    state = _state()
    if not state.config.auth.enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")

    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    email = body.get("email")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    if not state.db_session_factory:
        raise HTTPException(status_code=500, detail="Database not available")

    from .db import crud_users
    async with state.db_session_factory() as session:
        # Check if this is the first user (auto-admin)
        user_count = await crud_users.count_users(session)
        is_first_user = user_count == 0

        # If not first user, require admin token
        if not is_first_user:
            auth_header = request.headers.get("authorization", "")
            if not auth_header:
                raise HTTPException(status_code=401, detail="Admin token required")
            try:
                token = auth_header.removeprefix("Bearer ").strip()
                payload = decode_token(token, state.config.auth.secret_key)
                if payload.get("role") != "admin":
                    raise HTTPException(status_code=403, detail="Admin access required")
            except ValueError as e:
                raise HTTPException(status_code=401, detail=str(e))

        # Check for duplicate username
        existing = await crud_users.get_user_by_username(session, username)
        if existing:
            raise HTTPException(status_code=409, detail="Username already taken")

        # Create user
        role = body.get("role", "admin" if is_first_user else "user")
        pw_hash = hash_password(password)
        user = await crud_users.create_user(
            session, username=username, email=email,
            password_hash=pw_hash, role=role)

    # Return tokens
    token_data = {"sub": user["id"], "username": user["username"], "role": user["role"]}
    access_token = create_access_token(
        token_data, state.config.auth.secret_key,
        state.config.auth.access_token_expire_minutes)
    refresh_token = create_refresh_token(
        token_data, state.config.auth.secret_key,
        state.config.auth.refresh_token_expire_days)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
    }


@app.post("/auth/refresh")
async def auth_refresh(request: Request):
    """Refresh an access token using a valid refresh token."""
    from fastapi import HTTPException
    from .auth import decode_token, create_access_token, create_refresh_token

    state = _state()
    if not state.config.auth.enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")

    body = await request.json()
    refresh_token = body.get("refresh_token", "")

    if not refresh_token:
        raise HTTPException(status_code=400, detail="Refresh token required")

    try:
        payload = decode_token(refresh_token, state.config.auth.secret_key)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    # Issue new tokens
    token_data = {"sub": payload["sub"], "username": payload["username"], "role": payload["role"]}
    new_access = create_access_token(
        token_data, state.config.auth.secret_key,
        state.config.auth.access_token_expire_minutes)
    new_refresh = create_refresh_token(
        token_data, state.config.auth.secret_key,
        state.config.auth.refresh_token_expire_days)

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": state.config.auth.access_token_expire_minutes * 60,
    }


@app.get("/auth/me")
async def auth_me(authorization: str = Header(default="")):
    """Get current user info from JWT."""
    from fastapi import HTTPException
    from .auth import decode_token

    state = _state()
    if not state.config.auth.enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token, state.config.auth.secret_key)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return {
        "id": payload.get("sub"),
        "username": payload.get("username"),
        "role": payload.get("role"),
    }


# ── v5 Dashboard API endpoints ──────────────────────────────────────────

@app.get("/api/stats")
async def api_stats(authorization: str = Header(default="")):
    """Aggregated analytics: total requests, costs, tokens, per-model breakdown."""
    from fastapi import HTTPException

    state = _state()
    if not state.config.is_v5_mode or not state.db_session_factory:
        raise HTTPException(status_code=400, detail="v5 mode with database required")

    from .db import crud_logs, crud_analytics

    async with state.db_session_factory() as session:
        total_requests = await crud_logs.count_logs(session)
        cost_by_model = await crud_analytics.aggregate_costs(session)

    uptime = int(time.time() - state.start_time)
    return JSONResponse({
        "proxy": "codex-proxy",
        "version": __version__,
        "uptime_seconds": uptime,
        "requests_total": state.request_count,
        "success_count": state.success_count,
        "failure_count": state.failure_count,
        "db_requests_logged": total_requests,
        "cost_by_model": cost_by_model,
        "providers_count": len(state.providers_map),
    })


@app.get("/api/usage")
async def api_usage(request: Request, authorization: str = Header(default="")):
    """Cost and token usage over time, with optional ?model= filter."""
    from fastapi import HTTPException

    state = _state()
    if not state.config.is_v5_mode or not state.db_session_factory:
        raise HTTPException(status_code=400, detail="v5 mode with database required")

    from .db import crud_logs, crud_analytics

    model_filter = request.query_params.get("model")
    hours = int(request.query_params.get("hours", "24"))

    async with state.db_session_factory() as session:
        if model_filter:
            cost_data = await crud_analytics.aggregate_costs(session)
            cost_data = [c for c in cost_data if c.get("group_key") == model_filter]
        else:
            cost_data = await crud_analytics.aggregate_costs(session)

        total = await crud_logs.count_logs(session)

    return JSONResponse({
        "period_hours": hours,
        "model_filter": model_filter,
        "total_logged_requests": total,
        "cost_breakdown": cost_data,
    })


@app.get("/api/providers")
async def api_providers(authorization: str = Header(default="")):
    """Provider status with routing info."""
    state = _state()
    providers_info = []
    for name, ps in state.providers_map.items():
        info = {
            "name": name,
            "display_name": ps.config.display_name,
            "base_url": ps.base_url,
            "models": ps.config.models,
            "default_model": ps.config.default_model,
            "has_key_rotation": ps.key_rotator is not None,
        }
        providers_info.append(info)

    result: dict[str, Any] = {
        "providers": providers_info,
        "total": len(providers_info),
    }
    if state.smart_router:
        result["router"] = state.smart_router.get_status()
    return JSONResponse(result)


@app.get("/api/router/status")
async def api_router_status(authorization: str = Header(default="")):
    """Detailed smart router status and per-provider latency."""
    from fastapi import HTTPException

    state = _state()
    if not state.smart_router:
        raise HTTPException(status_code=400, detail="Router not enabled")

    return JSONResponse(state.smart_router.get_status())


def run(config: ProxyConfig, *, tui: bool = False) -> None:
    """Run the proxy server."""
    configure(config)
    level = getattr(logging, config.server.log_level.upper(), logging.WARNING)
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    if config.server.log_level == "debug":
        config.server.log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(config.server.log_dir / "proxy.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s"))
        logging.getLogger("codex-proxy").addHandler(fh)
    logger.info("codex-proxy v%s starting", __version__)

    if tui:
        from .tui import start_tui
        start_tui(app.state.proxy)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    else:
        print(f"  codex-proxy v{__version__}")
        print(f"  http://{config.server.host}:{config.server.port}")
        providers = config.all_providers()
        for p in providers:
            print(f"  provider  {p.display_name} ({p.base_url})")
            print(f"  models    {', '.join(p.models)}")
        if config.is_v5_mode:
            print(f"  mode      v5 (database={config.database.enabled}, auth={config.auth.enabled})")

    uvicorn.run(app, host=config.server.host, port=config.server.port,
                log_level=config.server.log_level)
