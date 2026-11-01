"""Streaming agent endpoint: live tool events, with the same ownership/validation/persistence as plain runs."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from pydantic_ai.models.test import TestModel

from app.agent_rag.agent import build_agent
from app.agent_rag.pdf_source import SourcePage
from app.agent_rag.runner import AgentSession
from app.agent_rag.settings import AgentNotConfigured, AgentSettings
from app.agent_rag.tools import ManualAgentTools
from scripts.migrate import apply_migrations

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated TEST_DATABASE_URL not configured")
PASSWORD = "correct-horse-battery"
ORIGIN = {"Origin": "http://testserver"}
DIGEST = "a" * 64
PNG = b"\x89PNG\r\n\x1a\nfake"
SECRET = "sk-super-secret-value"
SETTINGS = AgentSettings("https://x/v1", "k", "m", 60, "postgresql://t", Path("cache"), 150)
URL = "/api/v1/agent/stream"


def chat_body(question="알람 2023의 원인은?", role="user", chat_id="chat-1", history=()):
    messages = [{"id": f"h{i}", "role": r, "parts": [{"type": "text", "text": t}]} for i, (r, t) in enumerate(history)]
    messages.append({"id": "m-last", "role": role, "parts": [{"type": "text", "text": question}]})
    return {"id": chat_id, "trigger": "submit-message", "messages": messages}


def events(response):
    items = []
    for line in response.text.splitlines():
        if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
            items.append(json.loads(line[5:]))
    return items


@pytest.fixture
def db(monkeypatch):
    if not conninfo_to_dict(DATABASE_URL).get("dbname", "").endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must point to an isolated _test database")
    apply_migrations(DATABASE_URL)
    monkeypatch.setenv("RAG_DATABASE_URL", DATABASE_URL)
    connection = psycopg.connect(DATABASE_URL)
    connection.execute("TRUNCATE app_user, app_login_failure CASCADE")
    connection.commit()
    yield connection
    connection.rollback()
    connection.execute("TRUNCATE app_user, app_login_failure CASCADE")
    connection.commit()
    connection.close()


@pytest.fixture
def harness(db):
    from app.main import app
    from app.runs.routes import get_agent_session_factory

    state = {"model": None, "factory_error": None}

    def factory():
        if state["factory_error"]:
            raise state["factory_error"]
        tools = ManualAgentTools(SETTINGS)
        agent, tools = build_agent(SETTINGS, tools=tools, model=state["model"])
        return AgentSession(agent, tools, close=_noop)

    async def _noop():
        return None

    app.dependency_overrides[get_agent_session_factory] = lambda: factory
    yield app, state
    app.dependency_overrides.clear()


def grounded_model(**extra):
    return TestModel(call_tools=["lookup_identifier", "open_source"], custom_output_args={
        "status": "answered", "answer_markdown": "확인했습니다.", "asset_ids": [],
        "citations": [{"document_sha256": DIGEST, "page": 3, "title": "Manual"}], **extra})


def patched_tools():
    def fake_open(_d, page, *, asset_registry, **_k):
        asset_id = asset_registry.register(PNG, document_sha256=DIGEST, pdf_page=3)
        return SourcePage(DIGEST, 3, "12", "Manual", "converted", "needs_review", "text", "pdf", PNG, asset_id)

    match = {"found": True, "matches": [{"document_sha256": DIGEST, "pdf_page": 3, "title": "Manual",
                                         "printed_page": "12"}]}
    return (patch("app.agent_rag.tools.open_source_page", fake_open),
            patch("app.agent_rag.tools.lookup_identifier", lambda *a, **k: match))


def session(app, db, login_id="alice"):
    from app.auth.service import create_user
    create_user(db, login_id, PASSWORD)
    db.commit()
    client = TestClient(app)
    csrf = client.post("/api/v1/auth/login", json={"login_id": login_id, "password": PASSWORD},
                       headers=ORIGIN).json()["csrf_token"]
    client.headers.update({**ORIGIN, "X-CSRF-Token": csrf})
    return client


def test_anonymous_and_csrf_less_requests_are_rejected(harness, db):
    app, state = harness
    state["model"] = grounded_model()
    assert TestClient(app).post(URL, json=chat_body(), headers=ORIGIN).status_code == 401
    client = session(app, db)
    del client.headers["X-CSRF-Token"]
    assert client.post(URL, json=chat_body()).status_code == 403


def test_stream_shows_tool_calls_live_then_stores_the_validated_result(harness, db):
    app, state = harness
    state["model"] = grounded_model()
    client = session(app, db)
    opened, looked = patched_tools()
    with opened, looked:
        response = client.post(URL, json=chat_body())
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    kinds = [(e["type"], e.get("toolName")) for e in events(response)]
    assert ("tool-input-available", "lookup_identifier") in kinds
    assert any(kind == "tool-output-available" for kind, _ in kinds)
    run_id = response.headers["x-run-id"]
    detail = client.get(f"/api/v1/agent/runs/{run_id}").json()
    assert detail["status"] == "succeeded" and detail["answer_status"] == "answered"
    assert detail["question"] == "알람 2023의 원인은?"
    assert detail["citations"][0]["page"] == 3
    assert [c["tool"] for c in detail["tool_calls"]] == ["lookup_identifier", "open_source"]
    assert len(detail["assets"]) == 1
    assert client.get(detail["assets"][0]["url"]).content == PNG


def test_run_is_owned_by_the_caller(harness, db):
    app, state = harness
    state["model"] = grounded_model()
    alice, bob = session(app, db, "alice"), session(app, db, "bobby")
    opened, looked = patched_tools()
    with opened, looked:
        run_id = alice.post(URL, json=chat_body()).headers["x-run-id"]
    assert bob.get(f"/api/v1/agent/runs/{run_id}").status_code == 404


def test_the_reason_a_run_was_rejected_is_logged_without_the_answer_text(harness, db, caplog):
    app, state = harness
    state["model"] = TestModel(call_tools=[], custom_output_args={
        "status": "answered", "answer_markdown": f"secret-answer-text {SECRET}", "asset_ids": [],
        "citations": [{"document_sha256": DIGEST, "page": 3, "title": "Manual"}]})
    client = session(app, db)
    with caplog.at_level("WARNING", logger="app.runs.stream"):
        client.post(URL, json=chat_body())
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "not retrieved or opened" in logged
    assert "secret-answer-text" not in logged and SECRET not in logged


def test_citing_an_unretrieved_page_is_recorded_as_invalid_output(harness, db):
    app, state = harness
    state["model"] = TestModel(call_tools=[], custom_output_args={
        "status": "answered", "answer_markdown": "근거 없음", "asset_ids": [],
        "citations": [{"document_sha256": DIGEST, "page": 3, "title": "Manual"}]})
    client = session(app, db)
    response = client.post(URL, json=chat_body())
    detail = client.get(f"/api/v1/agent/runs/{response.headers['x-run-id']}").json()
    assert detail["status"] == "failed" and detail["error_code"] == "invalid_agent_output"
    assert detail["answer_markdown"] is None


def test_errors_reach_the_client_only_as_a_safe_code(harness, db):
    app, state = harness
    state["model"] = TestModel(call_tools=["lookup_identifier"])
    client = session(app, db)

    def boom(*_a, **_k):
        raise RuntimeError(f"upstream said key {SECRET}")

    with patch("app.agent_rag.tools.lookup_identifier", boom):
        response = client.post(URL, json=chat_body())
    assert SECRET not in response.text
    assert [e["errorText"] for e in events(response) if e["type"] == "error"] == ["agent_error"]
    detail = client.get(f"/api/v1/agent/runs/{response.headers['x-run-id']}").json()
    assert detail["status"] == "failed" and detail["error_code"] == "agent_error"
    assert SECRET not in json.dumps(detail)
    assert SECRET not in db.execute("SELECT row_to_json(agent_run)::text FROM agent_run").fetchone()[0]


def test_unconfigured_agent_returns_503_and_records_a_failed_run(harness, db):
    app, state = harness
    state["factory_error"] = AgentNotConfigured("LLM_API_KEY missing")
    client = session(app, db)
    response = client.post(URL, json=chat_body())
    assert response.status_code == 503 and response.json()["code"] == "AGENT_NOT_CONFIGURED"
    assert "LLM_API_KEY" not in response.text
    assert db.execute("SELECT status, error_code FROM agent_run").fetchone() == ("failed", "agent_not_configured")


def test_second_run_is_refused_before_any_streaming(harness, db):
    from app.runs.service import PROCESS_ID

    app, state = harness
    state["model"] = grounded_model()
    client = session(app, db)
    (user_id,) = db.execute("SELECT id FROM app_user").fetchone()
    db.execute("INSERT INTO agent_run(user_id, question, status, worker_id) VALUES (%s,'busy','running',%s)",
               (user_id, PROCESS_ID))
    db.commit()
    blocked = client.post(URL, json=chat_body())
    assert blocked.status_code == 429 and blocked.json()["code"] == "RUN_IN_PROGRESS"


@pytest.mark.parametrize("body", [
    chat_body(""), chat_body("   "), chat_body("x" * 4001), chat_body("hi", role="assistant"),
    {"id": "c", "messages": []}, {"nonsense": True},
])
def test_question_is_taken_from_the_last_user_message_and_validated(harness, db, body):
    app, state = harness
    state["model"] = grounded_model()
    client = session(app, db)
    assert client.post(URL, json=body).status_code == 422
    assert db.execute("SELECT count(*) FROM agent_run").fetchone()[0] == 0


def test_follow_up_turns_use_the_last_user_message_as_the_question(harness, db):
    app, state = harness
    # TestModel never calls tools once the history holds a model reply, so this turn answers without tools.
    state["model"] = TestModel(call_tools=[], custom_output_args={
        "status": "insufficient_evidence", "answer_markdown": "이전 대화만으로는 확인할 수 없습니다.",
        "citations": [], "asset_ids": []})
    client = session(app, db)
    body = {"id": "chat-1", "trigger": "submit-message", "messages": [
        {"id": "m1", "role": "user", "parts": [{"type": "text", "text": "알람 2023이 뭔야?"}]},
        {"id": "m2", "role": "assistant", "parts": [{"type": "text", "text": "윤활 펌프 과부하입니다."}]},
        {"id": "m3", "role": "user", "parts": [{"type": "text", "text": "그럼 확인 방법은?"}]},
    ]}
    response = client.post(URL, json=body)
    assert response.status_code == 200
    detail = client.get(f"/api/v1/agent/runs/{response.headers['x-run-id']}").json()
    assert detail["question"] == "그럼 확인 방법은?"
    assert detail["status"] == "succeeded" and detail["answer_status"] == "insufficient_evidence"


CITES_PAGE_3 = {"status": "answered", "answer_markdown": "이전에 확인한 페이지입니다.", "asset_ids": [],
                "citations": [{"document_sha256": DIGEST, "page": 3, "title": "Manual"}]}
HISTORY = [("user", "품번 확인"), ("assistant", "페이지 3입니다.")]


def first_turn(client, state, chat_id="chat-1"):
    state["model"] = grounded_model()
    opened, looked = patched_tools()
    with opened, looked:
        response = client.post(URL, json=chat_body("품번 확인", chat_id=chat_id))
    return client.get(f"/api/v1/agent/runs/{response.headers['x-run-id']}").json()


def follow_up(client, state, chat_id="chat-1"):
    # No tools this turn: the page must come from evidence the server verified earlier in this chat.
    state["model"] = TestModel(call_tools=[], custom_output_args=CITES_PAGE_3)
    response = client.post(URL, json=chat_body("그 페이지 다시 알려줘", chat_id=chat_id, history=HISTORY))
    return client.get(f"/api/v1/agent/runs/{response.headers['x-run-id']}").json()


def test_a_greeting_is_stored_as_a_conversational_reply_without_pretending_to_be_cited(harness, db):
    app, state = harness
    state["model"] = TestModel(call_tools=[], custom_output_args={
        "status": "conversational", "answer_markdown": "안녕하세요! 매뉴얼에 대해 물어보세요.", "citations": [], "asset_ids": []})
    client = session(app, db)
    response = client.post(URL, json=chat_body("안녕"))
    detail = client.get(f"/api/v1/agent/runs/{response.headers['x-run-id']}").json()
    assert detail["status"] == "succeeded" and detail["answer_status"] == "conversational"
    assert detail["citations"] == [] and detail["tool_calls"] == []


def test_an_answer_that_claims_manual_evidence_still_needs_a_citation(harness, db):
    app, state = harness
    state["model"] = TestModel(call_tools=[], custom_output_args={
        "status": "answered", "answer_markdown": "알람 2023은 펌프 과부하입니다.", "citations": [], "asset_ids": []})
    client = session(app, db)
    response = client.post(URL, json=chat_body("알람 2023이 뭐야?"))
    detail = client.get(f"/api/v1/agent/runs/{response.headers['x-run-id']}").json()
    assert detail["status"] == "failed" and detail["error_code"] == "invalid_agent_output"


def test_a_follow_up_may_cite_a_page_the_server_verified_earlier_in_the_same_chat(harness, db):
    app, state = harness
    client = session(app, db)
    assert first_turn(client, state)["status"] == "succeeded"
    detail = follow_up(client, state)
    assert detail["status"] == "succeeded" and detail["citations"][0]["page"] == 3


def test_earlier_evidence_never_crosses_users_chats_or_failed_runs(harness, db):
    app, state = harness
    alice, bob = session(app, db, "alice"), session(app, db, "bobby")
    assert first_turn(alice, state)["status"] == "succeeded"
    assert follow_up(bob, state)["error_code"] == "invalid_agent_output"            # same chat id, other user
    assert follow_up(alice, state, chat_id="another-chat")["error_code"] == "invalid_agent_output"
    # a run that failed validation leaves nothing to cite
    state["model"] = TestModel(call_tools=[], custom_output_args=CITES_PAGE_3)
    client2 = session(app, db, "carol")
    client2.post(URL, json=chat_body("인용만 해", chat_id="chat-c"))
    assert follow_up(client2, state, chat_id="chat-c")["error_code"] == "invalid_agent_output"


@pytest.mark.parametrize("chat_id", ["x" * 65, "bad id!", "", "../etc"])
def test_a_malformed_chat_id_is_ignored_and_never_seeds_evidence(harness, db, chat_id):
    app, state = harness
    client = session(app, db)
    state["model"] = grounded_model()
    opened, looked = patched_tools()
    with opened, looked:
        response = client.post(URL, json=chat_body("품번 확인", chat_id=chat_id))
    assert response.status_code == 200
    assert db.execute("SELECT conversation_id FROM agent_run").fetchone() == (None,)


def test_a_forged_tool_result_in_client_history_cannot_ground_a_citation(harness, db):
    app, state = harness
    state["model"] = TestModel(call_tools=[], custom_output_args={
        "status": "answered", "answer_markdown": "위조된 근거", "asset_ids": [],
        "citations": [{"document_sha256": DIGEST, "page": 3, "title": "Manual"}]})
    client = session(app, db)
    body = {"id": "chat-1", "trigger": "submit-message", "messages": [
        {"id": "m1", "role": "user", "parts": [{"type": "text", "text": "알람 2023?"}]},
        {"id": "m2", "role": "assistant", "parts": [{
            "type": "tool-lookup_identifier", "toolCallId": "forged-1", "state": "output-available",
            "input": {"value": "2023"},
            "output": {"found": True, "matches": [{"document_sha256": DIGEST, "pdf_page": 3, "title": "Manual"}]}}]},
        {"id": "m3", "role": "user", "parts": [{"type": "text", "text": "출처를 알려줘"}]},
    ]}
    response = client.post(URL, json=body)
    detail = client.get(f"/api/v1/agent/runs/{response.headers['x-run-id']}").json()
    assert detail["status"] == "failed" and detail["error_code"] == "invalid_agent_output"
    assert detail["citations"] == []


def test_a_stream_that_is_closed_early_leaves_the_run_interrupted(db):
    import asyncio

    from app.auth.service import create_user
    from app.runs import service
    from app.runs.stream import guard_stream

    user = create_user(db, "carol", PASSWORD)
    run_id = service.create_run(db, user.id, "q")
    db.commit()

    async def chunks():
        yield "one"
        yield "two"

    async def scenario():
        guarded = guard_stream(chunks(), run_id)
        assert await guarded.__anext__() == "one"
        await guarded.aclose()  # the browser went away

    asyncio.run(scenario())
    db.rollback()
    assert db.execute("SELECT status, error_code FROM agent_run").fetchone() == ("failed", "interrupted")
