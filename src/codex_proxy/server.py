"""FastAPI server — WebSocket + HTTP endpoints for Codex CLI."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
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


@dataclass
class AppState:
    config: ProxyConfig
    store: ResponseStore
    client: httpx.AsyncClient
    adapter: ProviderAdapter
    circuit_breaker: CircuitBreaker | None
    start_time: float = 0.0
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_request_time: float = 0.0
    key_rotator: KeyRotator | None = None
    plugin_registry: PluginRegistry | None = None
    rate_limiter: RateLimiter | None = None


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
    logger.info("codex-proxy shut down")


app = FastAPI(title="codex-proxy", lifespan=lifespan)


def configure(config: ProxyConfig) -> None:
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
    app.state.proxy = AppState(
        config=config, store=store, client=client,
        adapter=adapter, circuit_breaker=cb, start_time=time.time(),
        key_rotator=key_rotator,
        plugin_registry=_build_plugin_registry(config),
        rate_limiter=rate_limiter,
    )
    # CORS middleware (add only if origins configured)
    if config.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.server.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )


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


def _cc_headers(api_key: str) -> dict:
    state = _state()
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    h.update(state.config.provider.extra_headers)
    return state.adapter.adjust_headers(h)


def _backend_url() -> str:
    return _state().config.provider.base_url


async def _post_with_retry(url: str, json_body: dict, headers: dict) -> httpx.Response:
    """POST with retry on 5xx or transport errors."""
    state = _state()
    max_retries = state.config.server.max_retries
    retry_delay = state.config.server.retry_delay
    client = state.client
    for attempt in range(max_retries + 1):
        try:
            r = await client.post(url, json=json_body, headers=headers)
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
                                     headers: dict, api_key: str) -> httpx.Response:
    """POST with retry. On auth/rate-limit errors, rotate key and retry."""
    state = _state()
    if not state.key_rotator:
        return await _post_with_retry(url, json_body, headers)
    max_attempts = state.key_rotator.key_count
    r: httpx.Response | None = None
    for _ in range(max_attempts):
        r = await _post_with_retry(url, json_body, headers)
        if r.status_code in (401, 403, 429):
            state.key_rotator.record_failure(api_key, r.status_code)
            api_key = state.key_rotator.next_key()
            headers = _cc_headers(api_key)
            logger.warning("Key failed with %d, rotating", r.status_code)
            continue
        if r.status_code < 400:
            state.key_rotator.record_success(api_key)
        return r
    assert r is not None
    return r


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
    api_key = _api_key(authorization)

    cc_body = build_cc_request(
        body,
        compaction_enabled=state.config.compaction.enabled,
        compaction_max_messages=state.config.compaction.max_messages,
        compaction_keep_last=state.config.compaction.keep_last,
    )
    cc_body["model"] = model
    cc_body["stream"] = stream
    cc_body = state.adapter.adjust_request(cc_body)
    headers = _cc_headers(api_key)

    # Plugin: on_request
    req_id = uuid.uuid4().hex[:12]
    if state.plugin_registry:
        ctx = _build_plugin_ctx(req_id, "http", model, api_key, stream)
        await state.plugin_registry.on_request(ctx)

    if stream:
        result_holder: dict = {}
        original_input = body.get("input", [])

        async def _stream():
            async with state.client.stream("POST", f"{_backend_url()}/chat/completions",
                                           json=cc_body, headers=headers) as resp:
                if resp.status_code >= 400:
                    error_body = await resp.aread()
                    logger.error("Upstream error %d: %s", resp.status_code, error_body[:500])
                    if state.circuit_breaker:
                        state.circuit_breaker.record_failure()
                    state.failure_count += 1
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

        return StreamingResponse(_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    start_t = time.monotonic()
    r = await _request_with_key_failover(
        f"{_backend_url()}/chat/completions", cc_body, headers, api_key)
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
            cc_body = build_cc_request(
                body,
                compaction_enabled=state.config.compaction.enabled,
                compaction_max_messages=state.config.compaction.max_messages,
                compaction_keep_last=state.config.compaction.keep_last,
            )
            cc_body["model"] = model
            cc_body["stream"] = True
            cc_body = state.adapter.adjust_request(cc_body)
            headers = _cc_headers(api_key)

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
                async with state.client.stream(
                    "POST", f"{_backend_url()}/chat/completions",
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
    provider = _state().config.provider
    return JSONResponse({
        "object": "list",
        "data": [{"id": m, "object": "model",
                  "owned_by": provider.name}
                 for m in provider.models],
    })


@app.get("/health")
async def health(request: Request):
    state = _state()
    result: dict[str, Any] = {
        "status": "ok",
        "proxy": "codex-proxy",
        "version": __version__,
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
    provider = state.config.provider
    uptime = int(time.time() - state.start_time)
    result = {
        "proxy": "codex-proxy",
        "version": __version__,
        "status": "running",
        "uptime_seconds": uptime,
        "requests_total": state.request_count,
        "response_store_size": state.store.size(),
        "provider": {
            "name": provider.name,
            "display_name": provider.display_name,
            "base_url": provider.base_url,
            "models": provider.models,
            "default_model": provider.default_model,
        },
        "server": {
            "host": state.config.server.host,
            "port": state.config.server.port,
        },
    }
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
        print(f"  backend  {config.provider.display_name} ({config.provider.base_url})")
        print(f"  models   {', '.join(config.provider.models)}")

    uvicorn.run(app, host=config.server.host, port=config.server.port,
                log_level=config.server.log_level)
