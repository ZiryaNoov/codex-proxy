"""Responses API <-> Chat Completions protocol translator."""

from __future__ import annotations

import json
import time
import uuid

from .compaction import compact_messages

# ── Responses API input -> Chat Completions messages ────────────────────

def input_to_messages(input_data, instructions: str | None = None) -> list[dict]:
    """Convert Responses API `input` to Chat Completions `messages`."""
    messages: list[dict] = []
    if instructions:
        messages.append({"role": "system", "content": instructions})

    if isinstance(input_data, str):
        messages.append({"role": "user", "content": input_data})
        return messages

    if not isinstance(input_data, list):
        messages.append({"role": "user", "content": str(input_data)})
        return messages

    for item in input_data:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            continue

        t = item.get("type", "")

        if t == "message":
            role = item.get("role", "user")
            parts = item.get("content", [])
            text = ""
            for p in parts:
                if isinstance(p, str):
                    text += p
                elif isinstance(p, dict) and p.get("type") in ("input_text", "text"):
                    text += p.get("text", "")
            messages.append({"role": role, "content": text})

        elif t == "function_call":
            tc = {
                "id": item.get("call_id", item.get("id", "")),
                "type": "function",
                "function": {
                    "name": item.get("name", ""),
                    "arguments": item.get("arguments", "{}"),
                },
            }
            if (messages and messages[-1].get("role") == "assistant"
                    and "tool_calls" in messages[-1]):
                messages[-1]["tool_calls"].append(tc)
            else:
                messages.append({"role": "assistant", "content": None,
                                 "tool_calls": [tc]})

        elif t == "function_call_output":
            messages.append({"role": "tool",
                             "tool_call_id": item.get("call_id", ""),
                             "content": item.get("output", "")})

    return messages


# ── Tool format conversion ──────────────────────────────────────────────

def convert_tools(tools: list | None) -> list | None:
    """Convert Responses API tools -> Chat Completions tools."""
    if not tools:
        return None
    out = []
    for t in tools:
        tt = t.get("type", "")
        if tt == "function":
            fn = t.get("function", {})
            if not fn and t.get("name"):
                fn = {"name": t["name"],
                      "description": t.get("description", ""),
                      "parameters": t.get("parameters", {})}
            out.append({"type": "function", "function": fn})
    return out or None


# ── Request builder ─────────────────────────────────────────────────────

def build_cc_request(
    body: dict,
    compaction_enabled: bool = True,
    compaction_max_messages: int = 50,
    compaction_keep_last: int = 20,
) -> dict:
    """Parse Responses API body, return Chat Completions request dict."""
    model = body.get("model", "glm-5.1")
    messages = input_to_messages(body.get("input"), body.get("instructions"))
    if compaction_enabled:
        messages = compact_messages(
            messages,
            max_messages=compaction_max_messages,
            keep_last=compaction_keep_last,
        )
    cc: dict = {"model": model, "messages": messages,
                "stream": body.get("stream", True)}

    if cc["stream"]:
        cc["stream_options"] = {"include_usage": True}

    for k in ("temperature", "top_p"):
        if k in body:
            cc[k] = body[k]
    if "max_output_tokens" in body:
        cc["max_tokens"] = body["max_output_tokens"]
    elif "max_tokens" in body:
        cc["max_tokens"] = body["max_tokens"]

    tools = convert_tools(body.get("tools"))
    if tools:
        cc["tools"] = tools
    if "tool_choice" in body:
        cc["tool_choice"] = body["tool_choice"]

    return cc


def unwrap_envelope(raw: str) -> dict:
    """Parse JSON, unwrap Realtime API envelope if present."""
    body = json.loads(raw)
    if not isinstance(body, dict):
        return {}
    if body.get("type") == "response.create":
        res = body.get("response")
        if isinstance(res, dict):
            return res
    return body


# ── Response conversion: CC -> Responses API ────────────────────────────

def generate_response_id() -> str:
    return f"resp_{uuid.uuid4().hex[:24]}"


def cc_to_response(body: dict, model: str) -> dict:
    """Non-streaming Chat Completions response -> Responses API object."""
    out: list[dict] = []
    if body.get("choices"):
        msg = body["choices"][0].get("message", {})
        content = msg.get("content")
        reasoning = msg.get("reasoning_content")

        if reasoning:
            out.append({
                "type": "reasoning", "id": f"rs_{uuid.uuid4().hex[:24]}",
                "summary": [{"type": "summary_text", "text": reasoning}],
            })

        if content:
            out.append({
                "type": "message", "id": f"msg_{uuid.uuid4().hex[:24]}",
                "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": content,
                             "annotations": []}],
            })

        for tc in msg.get("tool_calls", []):
            out.append({
                "type": "function_call",
                "id": tc.get("id", ""), "call_id": tc.get("id", ""),
                "name": tc["function"]["name"],
                "arguments": tc["function"].get("arguments", "{}"),
            })

        if not content and not reasoning and not msg.get("tool_calls"):
            out.append({
                "type": "message", "id": f"msg_{uuid.uuid4().hex[:24]}",
                "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": "",
                             "annotations": []}],
            })

    usage = body.get("usage", {})
    return {
        "id": generate_response_id(), "object": "response",
        "created_at": int(time.time()), "model": model,
        "status": "completed", "output": out,
        "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                  "output_tokens": usage.get("completion_tokens", 0),
                  "total_tokens": usage.get("total_tokens", 0)},
    }


# ── Streaming core: shared parser + helpers ─────────────────────────────

async def parse_cc_stream(line_iter):
    """Core SSE parser — yields (event_type, data) tuples.

    Event types: "text", "reasoning", "tool_call", "usage"
    """
    async for line in line_iter:
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
                yield ("reasoning", rc)
            txt = delta.get("content")
            if txt:
                yield ("text", txt)
            for tc in delta.get("tool_calls", []):
                yield ("tool_call", tc)
        chunk_usage = chunk.get("usage")
        if chunk_usage:
            yield ("usage", chunk_usage)


def accumulate_tool_call(tool_calls: list[dict], tc: dict) -> None:
    """Accumulate a streaming tool_call delta into the tool_calls list."""
    idx = tc.get("index", 0)
    while len(tool_calls) <= idx:
        tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
    if tc.get("id"):
        tool_calls[idx]["id"] = tc["id"]
    fn = tc.get("function", {})
    if fn.get("name"):
        tool_calls[idx]["function"]["name"] = fn["name"]
    if fn.get("arguments"):
        tool_calls[idx]["function"]["arguments"] += fn["arguments"]


def build_final_output(mid: str, full_text: str, reasoning_text: str,
                       tool_calls: list[dict]) -> list[dict]:
    """Build the Responses API output list from accumulated stream data."""
    final_out: list[dict] = []
    if reasoning_text:
        final_out.append({
            "type": "reasoning", "id": f"rs_{uuid.uuid4().hex[:24]}",
            "summary": [{"type": "summary_text", "text": reasoning_text}],
        })
    final_out.append({
        "type": "message", "id": mid, "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": full_text,
                     "annotations": []}],
    })
    for tc in tool_calls:
        fc_id = tc["id"] or f"fc_{uuid.uuid4().hex[:24]}"
        final_out.append({
            "type": "function_call", "id": fc_id, "call_id": fc_id,
            "name": tc["function"]["name"],
            "arguments": tc["function"]["arguments"],
            "status": "completed",
        })
    return final_out


# ── Streaming: CC SSE -> Responses API SSE ──────────────────────────────

def _ev(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_cc_to_response(cc_iter, model: str, result: dict | None = None):
    """Convert Chat Completions SSE stream -> Responses API SSE events.

    If *result* is provided, it will be populated with the completed response
    dict (including id and output) after the generator finishes.
    """
    rid = generate_response_id()
    mid = f"msg_{uuid.uuid4().hex[:24]}"
    now = int(time.time())

    init = {"id": rid, "object": "response", "created_at": now,
            "model": model, "status": "in_progress", "output": [],
            "usage": {"input_tokens": 0, "output_tokens": 0,
                      "total_tokens": 0}}

    yield _ev("response.created", {"type": "response.created", "response": init})
    yield _ev("response.in_progress", {"type": "response.in_progress", "response": init})
    yield _ev("response.output_item.added", {
        "type": "response.output_item.added", "output_index": 0,
        "item": {"type": "message", "id": mid, "status": "in_progress",
                 "role": "assistant", "content": []}})
    yield _ev("response.content_part.added", {
        "type": "response.content_part.added", "output_index": 0,
        "content_index": 0,
        "part": {"type": "output_text", "text": "", "annotations": []}})

    full_text = ""
    reasoning_text = ""
    tool_calls: list[dict] = []
    usage_data = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    async for event_type, data in parse_cc_stream(cc_iter):
        if event_type == "reasoning":
            reasoning_text += data
        elif event_type == "text":
            full_text += data
            yield _ev("response.output_text.delta", {
                "type": "response.output_text.delta",
                "output_index": 0, "content_index": 0, "delta": data})
        elif event_type == "tool_call":
            accumulate_tool_call(tool_calls, data)
        elif event_type == "usage":
            usage_data = {
                "input_tokens": data.get("prompt_tokens", 0),
                "output_tokens": data.get("completion_tokens", 0),
                "total_tokens": data.get("total_tokens", 0),
            }

    # Finish text
    yield _ev("response.output_text.done", {
        "type": "response.output_text.done",
        "output_index": 0, "content_index": 0, "text": full_text})
    yield _ev("response.content_part.done", {
        "type": "response.content_part.done", "output_index": 0,
        "content_index": 0,
        "part": {"type": "output_text", "text": full_text, "annotations": []}})
    yield _ev("response.output_item.done", {
        "type": "response.output_item.done", "output_index": 0,
        "item": {"type": "message", "id": mid, "status": "completed",
                 "role": "assistant",
                 "content": [{"type": "output_text", "text": full_text,
                              "annotations": []}]}})

    # Build final output
    final_out = build_final_output(mid, full_text, reasoning_text, tool_calls)

    # Emit tool call items as separate events
    text_and_reasoning_count = len(final_out) - len(tool_calls)
    for i, item in enumerate(final_out[text_and_reasoning_count:], text_and_reasoning_count):
        fc = {k: v for k, v in item.items() if k != "status"}
        yield _ev("response.output_item.added", {
            "type": "response.output_item.added",
            "output_index": i, "item": fc})
        yield _ev("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": i, "item": fc})

    # Completed
    completed = {"id": rid, "object": "response", "created_at": now,
                 "model": model, "status": "completed", "output": final_out,
                 "usage": usage_data}
    yield _ev("response.completed", {
        "type": "response.completed", "response": completed})

    if result is not None:
        result["response"] = completed
