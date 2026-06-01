"""Tests for translator module — pure functions, no I/O."""


from codex_proxy.translator import (
    accumulate_tool_call,
    build_cc_request,
    build_final_output,
    cc_to_response,
    convert_tools,
    generate_response_id,
    input_to_messages,
    unwrap_envelope,
)

# ── input_to_messages ───────────────────────────────────────────────────

class TestInputToMessages:
    def test_string_input(self):
        msgs = input_to_messages("Hello")
        assert msgs == [{"role": "user", "content": "Hello"}]

    def test_string_with_instructions(self):
        msgs = input_to_messages("Hi", instructions="Be concise")
        assert msgs[0] == {"role": "system", "content": "Be concise"}
        assert msgs[1] == {"role": "user", "content": "Hi"}

    def test_list_of_messages(self):
        data = [
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "Hello"}]},
            {"type": "message", "role": "assistant",
             "content": [{"type": "text", "text": "Hi there"}]},
        ]
        msgs = input_to_messages(data)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "Hello"}
        assert msgs[1] == {"role": "assistant", "content": "Hi there"}

    def test_function_call(self):
        data = [
            {"type": "function_call", "call_id": "c1", "name": "read",
             "arguments": '{"path": "/tmp"}'},
        ]
        msgs = input_to_messages(data)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["tool_calls"][0]["function"]["name"] == "read"

    def test_function_call_output(self):
        data = [
            {"type": "function_call_output", "call_id": "c1",
             "output": "file contents"},
        ]
        msgs = input_to_messages(data)
        assert msgs[0] == {"role": "tool", "tool_call_id": "c1",
                           "content": "file contents"}

    def test_mixed_content(self):
        data = [
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "Do it"}]},
            {"type": "function_call", "call_id": "c1", "name": "run",
             "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1",
             "output": "done"},
        ]
        msgs = input_to_messages(data)
        assert len(msgs) == 3

    def test_empty_list(self):
        assert input_to_messages([]) == []

    def test_non_dict_items_skipped(self):
        assert input_to_messages([42, None]) == []

    def test_string_items_in_list(self):
        msgs = input_to_messages(["hello", "world"])
        assert len(msgs) == 2
        assert msgs[0]["content"] == "hello"


# ── convert_tools ───────────────────────────────────────────────────────

class TestConvertTools:
    def test_none(self):
        assert convert_tools(None) is None

    def test_empty_list(self):
        assert convert_tools([]) is None

    def test_function_tools(self):
        tools = [{"type": "function", "function": {
            "name": "read", "description": "Read file",
            "parameters": {"type": "object"}}}]
        result = convert_tools(tools)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "read"

    def test_inline_name(self):
        tools = [{"type": "function", "name": "write",
                  "description": "Write file", "parameters": {}}]
        result = convert_tools(tools)
        assert result[0]["function"]["name"] == "write"

    def test_non_function_type_skipped(self):
        tools = [{"type": "web_search", "query": "test"}]
        result = convert_tools(tools)
        assert result is None


# ── build_cc_request ────────────────────────────────────────────────────

class TestBuildCCRequest:
    def test_basic(self):
        body = {"model": "glm-5.1", "input": "test", "stream": False}
        cc = build_cc_request(body)
        assert cc["model"] == "glm-5.1"
        assert cc["stream"] is False
        assert cc["messages"] == [{"role": "user", "content": "test"}]

    def test_with_tools(self):
        body = {
            "model": "glm-5.1", "input": "do it",
            "tools": [{"type": "function", "function": {
                "name": "run", "parameters": {}}}],
        }
        cc = build_cc_request(body)
        assert "tools" in cc

    def test_temperature_passthrough(self):
        cc = build_cc_request({"input": "hi", "temperature": 0.5})
        assert cc["temperature"] == 0.5

    def test_max_output_tokens(self):
        cc = build_cc_request({"input": "hi", "max_output_tokens": 100})
        assert cc["max_tokens"] == 100

    def test_stream_options_included_when_streaming(self):
        cc = build_cc_request({"input": "hi", "stream": True})
        assert cc["stream_options"] == {"include_usage": True}

    def test_no_stream_options_when_not_streaming(self):
        cc = build_cc_request({"input": "hi", "stream": False})
        assert "stream_options" not in cc

    def test_tool_choice_passthrough(self):
        cc = build_cc_request({"input": "hi", "tool_choice": "auto",
                               "tools": [{"type": "function", "function": {
                                   "name": "run", "parameters": {}}}]})
        assert cc["tool_choice"] == "auto"

    def test_top_p_passthrough(self):
        cc = build_cc_request({"input": "hi", "top_p": 0.9})
        assert cc["top_p"] == 0.9

    def test_compaction_disabled(self):
        long_input = [{"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": f"msg{i}"}]}
                      for i in range(60)]
        cc = build_cc_request({"input": long_input, "stream": False},
                              compaction_enabled=False)
        assert len(cc["messages"]) == 60

    def test_compaction_custom_thresholds(self):
        long_input = [{"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": f"msg{i}"}]}
                      for i in range(40)]
        cc = build_cc_request(
            {"input": long_input, "stream": False},
            compaction_enabled=True,
            compaction_max_messages=30,
            compaction_keep_last=10,
        )
        assert len(cc["messages"]) == 11  # 1 compaction notice + 10 kept


# ── cc_to_response ──────────────────────────────────────────────────────

class TestCcToResponse:
    def test_text_response(self):
        body = {"choices": [{"message": {"content": "Hello"}}]}
        resp = cc_to_response(body, "glm-5.1")
        assert resp["status"] == "completed"
        assert resp["model"] == "glm-5.1"
        assert any(o["type"] == "message" for o in resp["output"])

    def test_reasoning_and_text(self):
        body = {"choices": [{"message": {
            "content": "Answer", "reasoning_content": "Thinking..."}}]}
        resp = cc_to_response(body, "glm-5.1")
        types = [o["type"] for o in resp["output"]]
        assert "reasoning" in types
        assert "message" in types

    def test_tool_calls(self):
        body = {"choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "tc1", "function": {
                "name": "read", "arguments": '{"path":"."}'}}]}}]}
        resp = cc_to_response(body, "glm-5.1")
        assert any(o["type"] == "function_call" for o in resp["output"])

    def test_empty_response(self):
        body = {"choices": [{"message": {}}]}
        resp = cc_to_response(body, "glm-5.1")
        assert len(resp["output"]) >= 1  # fallback empty message

    def test_usage_from_body(self):
        body = {"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                          "total_tokens": 15}}
        resp = cc_to_response(body, "glm-5.1")
        assert resp["usage"]["input_tokens"] == 10
        assert resp["usage"]["output_tokens"] == 5

    def test_reasoning_only_no_content(self):
        body = {"choices": [{"message": {"content": None,
                                          "reasoning_content": "Thinking..."}}]}
        resp = cc_to_response(body, "glm-5.1")
        types = [o["type"] for o in resp["output"]]
        assert "reasoning" in types

    def test_tool_calls_with_content(self):
        body = {"choices": [{"message": {
            "content": "I'll help",
            "tool_calls": [{"id": "tc1", "function": {
                "name": "run", "arguments": "{}"}}]}}]}
        resp = cc_to_response(body, "glm-5.1")
        types = [o["type"] for o in resp["output"]]
        assert "message" in types
        assert "function_call" in types


# ── unwrap_envelope ─────────────────────────────────────────────────────

class TestUnwrapEnvelope:
    def test_direct_body(self):
        body = unwrap_envelope('{"model":"glm-5.1","input":"hi"}')
        assert body["model"] == "glm-5.1"

    def test_envelope(self):
        body = unwrap_envelope(
            '{"type":"response.create","response":{"model":"glm-5.1","input":"hi"}}')
        assert body["model"] == "glm-5.1"
        assert "type" not in body or body.get("type") != "response.create"

    def test_envelope_missing_response_key(self):
        body = unwrap_envelope('{"type":"response.create"}')
        assert body["type"] == "response.create"


# ── generate_response_id ────────────────────────────────────────────────

class TestGenerateResponseId:
    def test_format(self):
        rid = generate_response_id()
        assert rid.startswith("resp_")
        assert len(rid) == 29  # resp_ + 24 hex chars

    def test_unique(self):
        ids = {generate_response_id() for _ in range(100)}
        assert len(ids) == 100


# ── accumulate_tool_call ────────────────────────────────────────────────

class TestAccumulateToolCall:
    def test_basic(self):
        calls = []
        accumulate_tool_call(calls, {"index": 0, "id": "tc1",
                                     "function": {"name": "read",
                                                  "arguments": '{"p":1}'}})
        assert calls[0]["id"] == "tc1"
        assert calls[0]["function"]["name"] == "read"

    def test_name_overwrite(self):
        calls = [{"id": "tc1", "function": {"name": "rea", "arguments": ""}}]
        accumulate_tool_call(calls, {"index": 0,
                                     "function": {"name": "read_file"}})
        assert calls[0]["function"]["name"] == "read_file"

    def test_arguments_concat(self):
        calls = [{"id": "", "function": {"name": "run", "arguments": '{"a"'}}]
        accumulate_tool_call(calls, {"index": 0,
                                     "function": {"arguments": ':1}'}})
        assert calls[0]["function"]["arguments"] == '{"a":1}'


# ── build_final_output ──────────────────────────────────────────────────

class TestBuildFinalOutput:
    def test_text_only(self):
        out = build_final_output("mid1", "Hello", "", [])
        assert len(out) == 1
        assert out[0]["type"] == "message"
        assert out[0]["content"][0]["text"] == "Hello"

    def test_with_reasoning(self):
        out = build_final_output("mid1", "Answer", "Thinking...", [])
        assert len(out) == 2
        assert out[0]["type"] == "reasoning"
        assert out[1]["type"] == "message"

    def test_with_tool_calls(self):
        tc = {"id": "tc1", "function": {"name": "run", "arguments": "{}"}}
        out = build_final_output("mid1", "", "", [tc])
        assert len(out) == 2  # message + function_call
        assert out[1]["type"] == "function_call"
        assert out[1]["status"] == "completed"
