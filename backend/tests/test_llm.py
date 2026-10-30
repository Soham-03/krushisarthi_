import json
from types import SimpleNamespace

import pytest

from app import llm
from .conftest import FakeServer

TOOLS = [{"name": "search_agri_knowledge", "description": "search", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}]


def _ok(text="", calls=None):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = [{"id": c[0], "type": "function", "function": {"name": c[1], "arguments": json.dumps(c[2])}} for c in calls]
    return 200, {"choices": [{"message": msg, "finish_reason": "stop"}]}


def test_openai_compat_request_and_text_response():
    srv = FakeServer(lambda p, r: _ok("Namaste"))
    try:
        p = llm.OpenAICompatProvider(srv.url, "secret-key", "some-model", 5)
        res = p.complete("SYSTEM TEXT", [{"role": "user", "content": "hi"}], TOOLS, 300)
        assert res.text == "Namaste" and res.tool_calls == []
        req = srv.requests[0]
        assert req["path"] == "/chat/completions"
        assert req["headers"]["Authorization"] == "Bearer secret-key"
        body = req["json"]
        assert body["model"] == "some-model" and body["max_tokens"] == 300
        assert body["messages"][0] == {"role": "system", "content": "SYSTEM TEXT"}
        assert body["tools"][0]["function"]["name"] == "search_agri_knowledge"
    finally:
        srv.close()


def test_openai_compat_tool_calls_and_tool_result_round_trip():
    srv = FakeServer(lambda p, r: _ok("", [("call_9", "search_agri_knowledge", {"query": "pink bollworm"})]))
    try:
        p = llm.OpenAICompatProvider(srv.url, "", "m", 5)
        res = p.complete("s", [{"role": "user", "content": "q"}], TOOLS, 100)
        assert res.tool_calls == [{"id": "call_9", "name": "search_agri_knowledge", "args": {"query": "pink bollworm"}}]
        assert "Authorization" not in srv.requests[0]["headers"]          # local models need no key
        history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "", "tool_calls": res.tool_calls},
                   {"role": "tool", "tool_call_id": "call_9", "name": "search_agri_knowledge", "content": '{"ok": true}'}]
        p.complete("s", history, TOOLS, 100)
        sent = srv.requests[1]["json"]["messages"]
        assert sent[2]["tool_calls"][0]["function"]["arguments"] == '{"query": "pink bollworm"}'
        assert sent[3] == {"role": "tool", "tool_call_id": "call_9", "content": '{"ok": true}'}
    finally:
        srv.close()


@pytest.mark.parametrize("status,kind", [(401, "auth"), (403, "auth"), (429, "rate_limit"), (400, "bad_request"), (404, "bad_request"), (500, "server"), (503, "server")])
def test_openai_compat_http_errors_are_classified(status, kind):
    srv = FakeServer(lambda p, r: (status, {"error": {"message": "nope"}}))
    try:
        with pytest.raises(llm.LLMError) as e:
            llm.OpenAICompatProvider(srv.url, "k", "m", 5).complete("s", [{"role": "user", "content": "x"}], [], 50)
        assert e.value.kind == kind and e.value.status == status
        assert "k" not in llm.user_message(e.value).split()      # message never echoes secrets
    finally:
        srv.close()


def test_openai_compat_bad_json_shape_and_network_and_timeout():
    srv = FakeServer(lambda p, r: (200, {"unexpected": True}))
    try:
        with pytest.raises(llm.LLMError) as e:
            llm.OpenAICompatProvider(srv.url, "", "m", 5).complete("s", [{"role": "user", "content": "x"}], [], 50)
        assert e.value.kind == "bad_response"
    finally:
        srv.close()
    with pytest.raises(llm.LLMError) as e:
        llm.OpenAICompatProvider("http://127.0.0.1:9", "", "m", 2).complete("s", [{"role": "user", "content": "x"}], [], 50)
    assert e.value.kind == "network"

    import time
    slow = FakeServer(lambda p, r: (time.sleep(1.2), _ok("late"))[1])
    try:
        with pytest.raises(llm.LLMError) as e:
            llm.OpenAICompatProvider(slow.url, "", "m", 0.3).complete("s", [{"role": "user", "content": "x"}], [], 50)
        assert e.value.kind == "timeout"
    finally:
        slow.close()


def test_anthropic_message_conversion_merges_tool_results():
    msgs = [{"role": "user", "content": "q"},
            {"role": "assistant", "content": "checking", "tool_calls": [{"id": "a", "name": "get_weather", "args": {}}, {"id": "b", "name": "get_soil_report", "args": {}}]},
            {"role": "tool", "tool_call_id": "a", "name": "get_weather", "content": "{}"},
            {"role": "tool", "tool_call_id": "b", "name": "get_soil_report", "content": "{}"}]
    out = llm.AnthropicProvider.convert(msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert [b["type"] for b in out[1]["content"]] == ["text", "tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["a", "b"]


def test_anthropic_response_parsing_with_stub_client():
    blocks = [SimpleNamespace(type="text", text="Looking it up."), SimpleNamespace(type="tool_use", id="t1", name="get_weather", input={})]
    seen = {}

    class Stub:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                seen.update(kw)
                return SimpleNamespace(content=blocks, stop_reason="tool_use")

    p = llm.AnthropicProvider.__new__(llm.AnthropicProvider)
    p.client, p.model = Stub(), "claude-test"
    res = p.complete("SYS", [{"role": "user", "content": "hi"}], TOOLS, 200)
    assert res.text == "Looking it up." and res.tool_calls == [{"id": "t1", "name": "get_weather", "args": {}}]
    assert seen["system"] == "SYS" and seen["model"] == "claude-test" and seen["tools"][0]["name"] == "search_agri_knowledge"


@pytest.mark.parametrize("status,kind", [(401, "auth"), (429, "rate_limit"), (400, "bad_request"), (529, "server"), (500, "server")])
def test_anthropic_errors_are_classified(status, kind):
    class Boom(Exception):
        status_code = status

    class Stub:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                raise Boom("failure")

    p = llm.AnthropicProvider.__new__(llm.AnthropicProvider)
    p.client, p.model = Stub(), "m"
    with pytest.raises(llm.LLMError) as e:
        p.complete("s", [{"role": "user", "content": "x"}], [], 10)
    assert e.value.kind == kind


def test_anthropic_timeout_and_connection_names():
    class APITimeoutError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    assert llm.map_anthropic_error(APITimeoutError("t")).kind == "timeout"
    assert llm.map_anthropic_error(APIConnectionError("c")).kind == "network"


def test_get_provider_requires_configuration(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(type(settings), "assistant_enabled", property(lambda self: False))
    with pytest.raises(llm.LLMError) as e:
        llm.get_provider()
    assert e.value.kind == "not_configured"
