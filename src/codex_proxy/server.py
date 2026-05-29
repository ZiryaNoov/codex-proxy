"""FastAPI server — WebSocket + HTTP endpoints for Codex CLI."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
import uvicorn
from fastapi import FastAPI, Request, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse

from . import __version__
from .config import ProxyConfig
from .store import ResponseStore
from .translator import (
    build_cc_request, cc_to_response, stream_cc_to_response,
    unwrap_envelope, generate_response_id,
    parse_cc_stream, accumulate_tool_call, build_final_output,
)

logger = logging.getLogger("codex-proxy")

MAX_RETRIES = 1
RETRY_DELAY = 0.5


@dataclass
class AppState:
    config: ProxyConfig
    store: ResponseStore
    client: httpx.AsyncClient
    start_time: float = 0.0
    request_count: int = 0


@asynccontextmanager
async def lifespan(app):
    yield
    state: AppState = app.state.proxy
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
        timeout=httpx.Timeout(connect=10, read=180, write=10, pool=30),
    )
    app.state.proxy = AppState(
        config=config, store=store, client=client,
        start_time=time.time(),
    )


def _state() -> AppState:
    return app.state.proxy


def _api_key(auth_header: str) -> str:
    if auth_header:
        lower = auth_header.lower()
        if lower.startswith("bearer "):
            return auth_header[7:].strip()
        return auth_header.strip()
    return _state().config.provider.effective_api_key()


def _cc_headers(api_key: str) -> dict:
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    h.update(_state().config.provider.extra_headers)
    return h


def _backend_url() -> str:
    return _state().config.provider.base_url


async def _post_with_retry(url: str, json_body: dict, headers: dict) -> httpx.Response:
    """POST with one retry on 5xx or transport errors."""
    client = _state().client
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = await client.post(url, json=json_body, headers=headers)
            if r.status_code < 500 or attempt == MAX_RETRIES:
                return r
            logger.warning("Upstream 5xx (attempt %d), retrying...", attempt + 1)
        except httpx.TransportError as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("Transport error (attempt %d): %s, retrying...", attempt + 1, e)
        await asyncio.sleep(RETRY_DELAY)
    raise httpx.TransportError("Max retries exceeded")


# ── HTTP endpoint ───────────────────────────────────────────────────────

@app.post("/responses")
async def responses_http(request: Request,
                         authorization: str = Header(default="")):
    state = _state()
    state.request_count += 1

    body = await request.json()
    body = state.store.resolve_input(body)
    model = body.get("model", state.config.provider.default_model)
    stream = body.get("stream", False)
    api_key = _api_key(authorization)

    cc_body = build_cc_request(body)
    cc_body["model"] = model
    cc_body["stream"] = stream
    headers = _cc_headers(api_key)

    if stream:
        result_holder: dict = {}
        original_input = body.get("input", [])

        async def _stream():
            async with state.client.stream("POST", f"{_backend_url()}/chat/completions",
                                           json=cc_body, headers=headers) as resp:
                if resp.status_code >= 400:
                    error_body = await resp.aread()
                    logger.error("Upstream error %d: %s", resp.status_code, error_body[:500])
                    yield f"event: error\ndata: {json.dumps({'error': {'message': 'upstream error', 'status': resp.status_code}})}\n\n"
                    return

                gen = stream_cc_to_response(resp.aiter_lines(), model, result=result_holder)
                async for chunk in gen:
                    yield chunk

            completed = result_holder.get("response")
            if completed:
                state.store.put(completed["id"], {**completed, "_original_input": original_input})

        return StreamingResponse(_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    r = await _post_with_retry(f"{_backend_url()}/chat/completions", cc_body, headers)
    if r.status_code >= 400:
        logger.error("Upstream error %d: %s", r.status_code, r.text[:500])
        return JSONResponse({"error": {"message": "upstream error",
                                       "status": r.status_code}},
                            status_code=502)

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
        api_key = state.config.provider.effective_api_key()

    try:
        while True:
            raw = await ws.receive_text()
            try:
                body = unwrap_envelope(raw)
            except json.JSONDecodeError:
                continue

            state.request_count += 1
            body = state.store.resolve_input(body)
            model = body.get("model", state.config.provider.default_model)
            cc_body = build_cc_request(body)
            cc_body["model"] = model
            cc_body["stream"] = True
            headers = _cc_headers(api_key)

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
    result = {
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
async def status():
    state = _state()
    provider = state.config.provider
    uptime = int(time.time() - state.start_time)
    return JSONResponse({
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
    })


@app.post("/reload")
async def reload_config():
    """Reload config from disk without restarting."""
    from .config import load_config
    state = _state()
    try:
        new_config = load_config()
        state.config = new_config
        if (new_config.store.ttl_seconds != state.store.ttl_seconds or
                new_config.store.max_entries != state.store.max_entries):
            state.store = ResponseStore(
                ttl_seconds=new_config.store.ttl_seconds,
                max_entries=new_config.store.max_entries,
            )
        logger.info("Config reloaded successfully")
        return {"status": "reloaded", "provider": new_config.provider.display_name,
                "model": new_config.provider.default_model}
    except Exception as e:
        logger.error("Config reload failed: %s", e)
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500,
        )


def run(config: ProxyConfig) -> None:
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
    print(f"  codex-proxy v{__version__}")
    print(f"  http://{config.server.host}:{config.server.port}")
    print(f"  backend  {config.provider.display_name} ({config.provider.base_url})")
    print(f"  models   {', '.join(config.provider.models)}")
    uvicorn.run(app, host=config.server.host, port=config.server.port,
                log_level=config.server.log_level)
