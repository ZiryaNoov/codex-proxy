"""Tests for ResponseStore."""

import time
from unittest.mock import patch

import pytest

from codex_proxy.store import ResponseStore


class TestStorePutGet:
    def test_basic(self):
        s = ResponseStore()
        s.put("r1", {"id": "r1", "output": []})
        assert s.get("r1") is not None
        assert s.get("r1")["id"] == "r1"

    def test_missing(self):
        s = ResponseStore()
        assert s.get("nonexistent") is None


class TestTTLExpiry:
    def test_expired(self):
        s = ResponseStore(ttl_seconds=10)
        s.put("r1", {"id": "r1"})
        # Simulate time passing beyond TTL
        with patch("codex_proxy.store.time.time", return_value=time.time() + 11):
            assert s.get("r1") is None

    def test_not_expired(self):
        s = ResponseStore(ttl_seconds=600)
        s.put("r1", {"id": "r1"})
        with patch("codex_proxy.store.time.time", return_value=time.time() + 100):
            assert s.get("r1") is not None


class TestMaxEntries:
    def test_eviction(self):
        s = ResponseStore(max_entries=5)
        for i in range(6):
            s.put(f"r{i}", {"id": f"r{i}"})
        # First entry should be evicted
        assert s.get("r0") is None
        assert s.get("r5") is not None
        assert s.size() == 5


class TestResolveInput:
    def test_no_previous(self):
        s = ResponseStore()
        body = {"input": "hello"}
        result = s.resolve_input(body)
        assert result == body

    def test_with_previous(self):
        s = ResponseStore()
        s.put("r1", {
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text",
                                     "text": "Hi"}]}],
            "_original_input": [{"type": "message", "role": "user",
                                 "content": [{"type": "input_text",
                                              "text": "Hello"}]}],
        })
        body = {"previous_response_id": "r1", "input": "Next question"}
        result = s.resolve_input(body)
        assert "previous_response_id" not in result
        assert len(result["input"]) == 3  # prev_input + prev_output_as_context + current

    def test_expired_previous(self):
        s = ResponseStore(ttl_seconds=10)
        s.put("r1", {"output": [], "_original_input": []})
        with patch("codex_proxy.store.time.time", return_value=time.time() + 11):
            body = {"previous_response_id": "r1", "input": "hello"}
            result = s.resolve_input(body)
            assert result["input"] == "hello"


class TestSize:
    def test_empty(self):
        assert ResponseStore().size() == 0

    def test_after_puts(self):
        s = ResponseStore()
        s.put("r1", {"id": "r1"})
        s.put("r2", {"id": "r2"})
        assert s.size() == 2
