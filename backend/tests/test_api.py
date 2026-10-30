import pytest

from app import llm, rag
from app.config import settings
from .conftest import COTTON_DOC, R, Scripted, call


@pytest.fixture()
def ai_on(monkeypatch):
    """Switch the assistant on and let each test choose what the model API does."""
    monkeypatch.setattr(type(settings), "assistant_enabled", property(lambda self: True))

    def use(provider):
        monkeypatch.setattr(llm, "get_provider", lambda: provider)
        return provider
    return use


def chat(client, farm, message="hello", **kw):
    return client.post("/api/chat", json={"farm_id": farm["id"], "message": message, "history": kw.get("history", []), "language": kw.get("language", "en")})


def test_config_reports_assistant_and_knowledge_base(client):
    cfg = client.get("/api/config").json()
    assert cfg["assistant"] is False and cfg["kb"]["available"] is True and cfg["kb"]["documents"] == 0
    assert "ANTHROPIC" not in str(cfg) and "api_key" not in str(cfg).lower()


def test_without_a_provider_the_basic_helper_answers_and_says_so(client, farm):
    r = chat(client, farm, "why is growth low?")
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "offline" and body["sources"] == [] and "offline" in body["notes"]


def test_chat_end_to_end_returns_reply_sources_and_tool_trace(client, farm, ai_on):
    rag.add_document({"title": "Cotton pest guide", "publisher": "Test University", "url": "https://example.test/c", "published": "2024-05-01", "crops": ["cotton"]}, [(2, COTTON_DOC)])
    ai_on(Scripted([R("", [call("search_agri_knowledge", {"query": "pink bollworm cotton"}), call("get_farm_profile", cid="c2")]), R("Use pheromone traps [S1].")]))
    r = chat(client, farm, "pink bollworm?")
    b = r.json()
    assert r.status_code == 200 and b["mode"] == "ai" and b["grounded"] is True
    assert b["sources"][0]["title"] == "Cotton pest guide" and b["sources"][0]["cited"] is True
    assert [t["name"] for t in b["tools"]] == ["search_agri_knowledge", "get_farm_profile"]


def test_follow_up_through_the_api_keeps_context(client, farm, ai_on):
    p = ai_on(Scripted([R("Which leaves are affected?"), R("Then it is likely whitefly.")]))
    first = chat(client, farm, "my leaves curl").json()["reply"]
    chat(client, farm, "the young ones", history=[{"role": "user", "content": "my leaves curl"}, {"role": "assistant", "content": first}])
    assert [m["role"] for m in p.calls[1]["messages"]] == ["user", "assistant", "user"]


@pytest.mark.parametrize("kind,status", [("rate_limit", 429), ("auth", 502), ("bad_request", 502), ("server", 502), ("timeout", 504), ("network", 502)])
def test_provider_failures_become_clear_errors(client, farm, ai_on, kind, status):
    ai_on(Scripted([llm.LLMError(kind, "internal detail sk-secret-123", status)]))
    r = chat(client, farm)
    assert r.status_code == status or (kind == "rate_limit" and r.status_code == 429)
    detail = r.json()["detail"]
    assert detail == llm.USER_MESSAGES[kind] and "sk-secret" not in r.text


def test_failure_in_the_middle_of_a_tool_loop_is_reported(client, farm, ai_on):
    ai_on(Scripted([R("", [call("get_farm_profile")]), llm.LLMError("timeout", "slow")]))
    assert chat(client, farm).status_code == 504


def test_unconfigured_model_name_surfaces_as_bad_request(client, farm, ai_on):
    ai_on(Scripted([llm.LLMError("bad_request", "model not found", 404)]))
    assert "model name" in chat(client, farm).json()["detail"]


def test_chat_rate_limit(client, farm, ai_on, monkeypatch):
    monkeypatch.setattr(settings, "chat_rate_per_minute", 2)
    ai_on(Scripted([R("a"), R("b"), R("c")]))
    assert [chat(client, farm).status_code for _ in range(3)] == [200, 200, 429]


def test_other_peoples_farms_and_bad_input_are_rejected(client, farm, ai_on):
    ai_on(Scripted([R("x")]))
    assert client.post("/api/chat", json={"farm_id": 999999, "message": "hi"}).status_code == 404
    assert client.post("/api/chat", json={"farm_id": farm["id"], "message": ""}).status_code == 422
    assert client.post("/api/chat", json={"farm_id": farm["id"], "message": "x" * 2000}).status_code == 422


def test_unknown_language_falls_back_to_english(client, farm, ai_on):
    p = ai_on(Scripted([R("ok")]))
    chat(client, farm, language="fr")
    assert "English" in p.calls[0]["system"]


def test_kb_endpoints_list_sources(client):
    rag.add_document({"title": "Cotton pest guide", "publisher": "Test University", "published": "2024-05-01"}, [(1, COTTON_DOC)])
    assert client.get("/api/kb/status").json()["documents"] == 1
    docs = client.get("/api/kb/documents").json()
    assert docs[0]["title"] == "Cotton pest guide" and docs[0]["publisher"] == "Test University"


def test_existing_farm_features_still_work(client, farm):
    ov = client.get(f"/api/farms/{farm['id']}/overview").json()
    assert ov["satellite"]["status"] in ("normal", "watch", "abnormal") and ov["weather"]["days"] and ov["diagnosis"]["causes"] is not None
    assert any(f["id"] == farm["id"] for f in client.get("/api/farms").json())
