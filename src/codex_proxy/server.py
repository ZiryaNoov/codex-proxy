"""FastAPI server — WebSocket + HTTP endpoints for Codex CLI."""

from __future__ import annotations

import json
import logging
import time
import uuid

import httpx
import uvicorn
from fastapi import FastAPI, Request, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse

from . import __version__
from .config import ProxyConfig
from .store import ResponseStore
from .translator import (
    build_cc_request, cc_to_response, stream_cc_to_response,
    unwrap_envelope, _rid,
)

logger = logging.getLogger("codex-proxy")

app = FastAPI(title="codex-proxy")

# Global state — set by configure()
_config: ProxyConfig | None = None
_store = ResponseStore()
_client: httpx.AsyncClient | None = None
_start_time = 0.0
_request_count = 0


def configure(config: ProxyConfig) -> None:
    global _config, _start_time, _client
    _config = config
    _start_time = time.time()
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=180, write=10, pool=30),
    )


def _api_key(auth_header: str) -> str:
    if auth_header:
        lower = auth_header.lower()
        if lower.startswith("bearer "):
            return auth_header[7:].strip()
        return auth_header.strip()
    return _config.provider.effective_api_key() if _config else ""


def _cc_headers(api_key: str) -> dict:
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if _config:
        h.update(_config.provider.extra_headers)
    return h


def _backend_url() -> str:
    return _config.provider.base_url if _config else "https://api.z.ai/api/paas/v4"


# ── HTTP endpoint ───────────────────────────────────────────────────────

@app.post("/responses")
async def responses_http(request: Request,
                         authorization: str = Header(default="")):
    global _request_count
    _request_count += 1

    body = await request.json()
    body = _store.resolve_input(body)
    model = body.get("model", _config.provider.default_model if _config else "glm-5.1")
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
            async with _client.stream("POST", f"{_backend_url()}/chat/completions",
                                      json=cc_body, headers=headers) as resp:
                if resp.status_code >= 400:
                    error_body = await resp.aread()
                    logger.error("Upstream error %d: %s", resp.status_code, error_body[:500])
                    yield f"event: error\ndata: {json.dumps({'error': {'message': 'upstream error', 'status': resp.status_code}})}\n\n"
                    return

                gen = stream_cc_to_response(resp.aiter_lines(), model, result=result_holder)
                async for chunk in gen:
                    yield chunk

            # Store after streaming completes
            completed = result_holder.get("response")
            if completed:
                _store.put(completed["id"], {**completed, "_original_input": original_input})

        return StreamingResponse(_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    r = await _client.post(f"{_backend_url()}/chat/completions",
                           json=cc_body, headers=headers)
    if r.status_code >= 400:
        logger.error("Upstream error %d: %s", r.status_code, r.text[:500])
        return JSONResponse({"error": {"message": "upstream error",
                                       "status": r.status_code}},
                            status_code=502)

    resp = cc_to_response(r.json(), model)
    _store.put(resp["id"], {**resp, "_original_input": body.get("input", [])})
    return JSONResponse(resp)


# ── WebSocket endpoint ──────────────────────────────────────────────────

@app.websocket("/responses")
async def responses_ws(ws: WebSocket):
    global _request_count

    await ws.accept()
    api_key = ""
    auth = ws.headers.get("authorization", "")
    if auth:
        api_key = _api_key(auth)
    if not api_key and _config:
        api_key = _config.provider.effective_api_key()

    try:
        while True:
            raw = await ws.receive_text()
            try:
                body = unwrap_envelope(raw)
            except json.JSONDecodeError:
                continue

            _request_count += 1
            body = _store.resolve_input(body)
            model = body.get("model",
                             _config.provider.default_model if _config else "glm-5.1")
            cc_body = build_cc_request(body)
            cc_body["model"] = model
            cc_body["stream"] = True
            headers = _cc_headers(api_key)

            rid = _rid()
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
                async with _client.stream(
                    "POST", f"{_backend_url()}/chat/completions",
                    json=cc_body, headers=headers
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta", {})
                            rc = delta.get("reasoning_content")
                            if rc:
                                reasoning_text += rc
                            txt = delta.get("content")
                            if txt:
                                full_text += txt
                                await ws.send_text(json.dumps({
                                    "type": "response.output_text.delta",
                                    "output_index": 0,
                                    "content_index": 0, "delta": txt}))
                            for tc in delta.get("tool_calls", []):
                                idx = tc.get("index", 0)
                                while len(tool_calls) <= idx:
                                    tool_calls.append(
                                        {"id": "",
                                         "function": {"name": "",
                                                      "arguments": ""}})
                                if tc.get("id"):
                                    tool_calls[idx]["id"] = tc["id"]
                                fn = tc.get("function", {})
                                if fn.get("name"):
                                    tool_calls[idx]["function"]["name"] = fn["name"]
                                if fn.get("arguments"):
                                    tool_calls[idx]["function"]["arguments"] += fn["arguments"]
                        chunk_usage = chunk.get("usage")
                        if chunk_usage:
                            usage_data = {
                                "input_tokens": chunk_usage.get("prompt_tokens", 0),
                                "output_tokens": chunk_usage.get("completion_tokens", 0),
                                "total_tokens": chunk_usage.get("total_tokens", 0),
                            }
            except Exception as e:
                logger.error("WS upstream error: %s", e)

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

            # Build final output
            final_out: list[dict] = []
            if reasoning_text:
                final_out.append({
                    "type": "reasoning",
                    "id": f"rs_{uuid.uuid4().hex[:24]}",
                    "summary": [{"type": "summary_text",
                                 "text": reasoning_text}],
                })
            final_out.append({
                "type": "message", "id": mid, "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": full_text,
                             "annotations": []}]})

            for i, tc in enumerate(tool_calls):
                fc_id = tc["id"] or f"fc_{uuid.uuid4().hex[:24]}"
                fc = {"type": "function_call", "id": fc_id,
                      "call_id": fc_id,
                      "name": tc["function"]["name"],
                      "arguments": tc["function"]["arguments"]}
                oi = len(final_out)
                await ws.send_text(json.dumps({
                    "type": "response.output_item.added",
                    "output_index": oi, "item": fc}))
                await ws.send_text(json.dumps({
                    "type": "response.output_item.done",
                    "output_index": oi, "item": fc}))
                final_out.append({**fc, "status": "completed"})

            completed = {"id": rid, "object": "response",
                         "created_at": now, "model": model,
                         "status": "completed", "output": final_out,
                         "usage": usage_data}
            await ws.send_text(json.dumps(
                {"type": "response.completed",
                 "response": completed}))

            _store.put(rid, {**completed,
                             "_original_input": body.get("input", [])})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)


# ── Utility endpoints ───────────────────────────────────────────────────

@app.get("/models")
@app.get("/v1/models")
async def models():
    provider = _config.provider if _config else None
    model_list = provider.models if provider else ["glm-5.1"]
    return JSONResponse({
        "object": "list",
        "data": [{"id": m, "object": "model",
                  "owned_by": provider.name if provider else "proxy"}
                 for m in model_list],
    })


@app.get("/health")
async def health():
    return {"status": "ok", "proxy": "codex-proxy",
            "version": __version__}


@app.get("/status")
async def status():
    provider = _config.provider if _config else None
    uptime = int(time.time() - _start_time) if _start_time else 0
    return JSONResponse({
        "proxy": "codex-proxy",
        "version": __version__,
        "status": "running",
        "uptime_seconds": uptime,
        "requests_total": _request_count,
        "response_store_size": _store.size(),
        "provider": {
            "name": provider.name if provider else "unknown",
            "display_name": provider.display_name if provider else "Unknown",
            "base_url": provider.base_url if provider else "",
            "models": provider.models if provider else [],
            "default_model": provider.default_model if provider else "",
        },
        "server": {
            "host": _config.server.host if _config else "127.0.0.1",
            "port": _config.server.port if _config else 4242,
        },
    })


def run(config: ProxyConfig) -> None:
    """Run the proxy server."""
    configure(config)
    level = getattr(logging, config.server.log_level.upper(), logging.WARNING)
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    logger.info("codex-proxy v%s starting", __version__)
    print(f"  codex-proxy v{__version__}")
    print(f"  http://{config.server.host}:{config.server.port}")
    print(f"  backend  {config.provider.display_name} ({config.provider.base_url})")
    print(f"  models   {', '.join(config.provider.models)}")
    uvicorn.run(app, host=config.server.host, port=config.server.port,
                log_level=config.server.log_level)
