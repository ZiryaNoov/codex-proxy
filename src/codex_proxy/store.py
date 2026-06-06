"""In-memory response store for previous_response_id support."""

from __future__ import annotations

import time
from collections import OrderedDict


class ResponseStore:
    """Stores completed responses so Codex can reference them in multi-turn."""

    def __init__(self, ttl_seconds: int = 600, max_entries: int = 100):
        self._store: OrderedDict[str, dict] = OrderedDict()
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries

    def put(self, response_id: str, response: dict) -> None:
        self._store[response_id] = {
            "response": response,
            "timestamp": time.time(),
        }
        if len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def get(self, response_id: str) -> dict | None:
        entry = self._store.get(response_id)
        if not entry:
            return None
        if time.time() - entry["timestamp"] > self.ttl_seconds:
            del self._store[response_id]
            return None
        res = entry["response"]
        if not isinstance(res, dict):
            return None
        return res

    def resolve_input(self, body: dict) -> dict:
        """If body has previous_response_id, prepend that response's output to input."""
        prev_id = body.get("previous_response_id")
        if not prev_id:
            return body

        prev = self.get(prev_id)
        if not prev:
            return body

        current_input = body.get("input", [])
        prev_output = prev.get("output", [])

        # Convert previous output items to input items for context
        context_items = []
        for item in prev_output:
            t = item.get("type", "")
            if t == "message":
                role = item.get("role", "assistant")
                parts = item.get("content", [])
                text = ""
                for p in parts:
                    if isinstance(p, dict):
                        text += p.get("text", "")
                if text:
                    context_items.append({
                        "type": "message", "role": role,
                        "content": [{"type": "input_text", "text": text}]
                    })
            elif t == "function_call":
                context_items.append({
                    "type": "function_call",
                    "id": item.get("id", ""),
                    "call_id": item.get("call_id", ""),
                    "name": item.get("name", ""),
                    "arguments": item.get("arguments", "{}"),
                })

        # Get previous input (the conversation before the response)
        prev_input = prev.get("_original_input", [])

        # Combine: previous input + previous output + current input
        combined = prev_input + context_items
        if isinstance(current_input, list):
            combined += current_input
        elif isinstance(current_input, str):
            combined.append({"type": "message", "role": "user",
                             "content": [{"type": "input_text",
                                          "text": current_input}]})

        body = dict(body)
        body["input"] = combined
        body.pop("previous_response_id", None)
        return body

    def size(self) -> int:
        return len(self._store)

    def clear(self) -> int:
        """Clear all entries. Returns count of cleared entries."""
        count = len(self._store)
        self._store.clear()
        return count

    def entries(self) -> list[tuple[str, float]]:
        """Return list of (response_id, age_seconds) for all cached entries."""
        now = time.time()
        return [(rid, now - entry["timestamp"]) for rid, entry in self._store.items()]
