"""Stage 2: logged-in users start agent runs; only the owner can read results and images."""
import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from app.agent_rag.agent import ManualAgentResult
from app.agent_rag.assets import SourceAsset
from scripts.migrate import apply_migrations

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated TEST_DATABASE_URL not configured")
PASSWORD = "correct-horse-battery"
ORIGIN = {"Origin": "http://testserver"}
DIGEST = "a" * 64
PNG = b"\x89PNG\r\n\x1a\nfake-page-image"
SECRET = "sk-super-secret-value"


def sample_result() -> ManualAgentResult:
    return ManualAgentResult(
        answer_markdown="확인했습니다. ![](asset:asset-1)",
        citations=({"document_sha256": DIGEST, "page": 3, "printed_page": "12", "title": "Manual"},),
        assets=(SourceAsset("asset-1", PNG, DIGEST, 3),),
        tool_calls=({"tool": "search_manual", "status": "ok", "result_count": 2,
                     "search_status": {"exact_identifier": "not_detected", "keyword": "ok"}},
                    {"tool": "open_source", "document_sha256": DIGEST, "pdf_page": 3}),
        status="answered",
        case_citations=({"fsr_no": "FSR-00001", "machine": "VMCT-02", "registered_on": "2012-01-06"},),
    )


@pytest.fixture
def db(monkeypatch):
    from db_safety import require_disposable_test_database
    require_disposable_test_database(DATABASE_URL)
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
def app_with_runner(db):
    from app.main import app
    from app.runs.routes import get_agent_runner

    state = {"runner": None, "questions": []}

    async def fake_runner(question):
        state["questions"].append(question)
        return await state["runner"](question)

    async def ok(_question):
        return sample_result()

    state["runner"] = ok
    app.dependency_overrides[get_agent_runner] = lambda: fake_runner
    yield app, state
    app.dependency_overrides.clear()


def session(app, db, login_id="alice", role="admin"):
    from app.auth.service import create_user
    create_user(db, login_id, PASSWORD, role=role)
    db.commit()
    client = TestClient(app)
    csrf = client.post("/api/v1/auth/login", json={"login_id": login_id, "password": PASSWORD},
                       headers=ORIGIN).json()["csrf_token"]
    client.headers.update({**ORIGIN, "X-CSRF-Token": csrf})
    return client


def start(client, question="알람 2023의 원인은?"):
    return client.post("/api/v1/agent/runs", json={"question": question})


def test_anonymous_and_csrf_less_requests_are_rejected(app_with_runner, db):
    app, _ = app_with_runner
    assert TestClient(app).post("/api/v1/agent/runs", json={"question": "q"}, headers=ORIGIN).status_code == 401
    assert TestClient(app).get("/api/v1/agent/runs").status_code == 401
    client = session(app, db)
    del client.headers["X-CSRF-Token"]
    assert start(client).status_code == 403


def test_user_role_is_a_customer_and_cannot_use_the_agent(app_with_runner, db):
    app, state = app_with_runner
    customer = session(app, db, "bob", role="user")
    denied = start(customer)
    assert denied.status_code == 403
    assert denied.json()["code"] == "OPERATOR_REQUIRED"
    assert customer.get("/api/v1/agent/runs").status_code == 403
    assert "runner" in state  # the agent was never invoked


def test_run_completes_and_stores_answer_citations_tools_and_images(app_with_runner, db):
    app, state = app_with_runner
    client = session(app, db)
    created = start(client)
    assert created.status_code == 202
    run_id = created.json()["id"]
    assert state["questions"] == ["알람 2023의 원인은?"]
    detail = client.get(f"/api/v1/agent/runs/{run_id}").json()
    assert detail["status"] == "succeeded" and detail["answer_status"] == "answered"
    assert detail["answer_markdown"].startswith("확인했습니다.")
    assert detail["citations"][0]["page"] == 3
    assert detail["case_citations"] == [{"fsr_no": "FSR-00001", "machine": "VMCT-02",
                                         "registered_on": "2012-01-06"}]
    assert [call["tool"] for call in detail["tool_calls"]] == ["search_manual", "open_source"]
    assert detail["retrieval_status"] == [{"exact_identifier": "not_detected", "keyword": "ok"}]
    asset = detail["assets"][0]
    assert asset["asset_id"] == "asset-1" and asset["url"] == f"/api/v1/agent/runs/{run_id}/assets/asset-1"
    assert "data" not in asset


def test_asset_endpoint_serves_the_png_with_safe_headers(app_with_runner, db):
    app, _ = app_with_runner
    client = session(app, db)
    run_id = start(client).json()["id"]
    image = client.get(f"/api/v1/agent/runs/{run_id}/assets/asset-1")
    assert image.status_code == 200 and image.content == PNG
    assert image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"
    assert "private" in image.headers["cache-control"]
    assert client.get(f"/api/v1/agent/runs/{run_id}/assets/not-opened").status_code == 404


def test_other_users_cannot_read_list_or_download_a_run(app_with_runner, db):
    app, _ = app_with_runner
    alice = session(app, db, "alice")
    bob = session(app, db, "bobby")
    run_id = start(alice).json()["id"]
    assert bob.get(f"/api/v1/agent/runs/{run_id}").status_code == 404
    assert bob.get(f"/api/v1/agent/runs/{run_id}/assets/asset-1").status_code == 404
    assert bob.get("/api/v1/agent/runs").json() == {"runs": []}
    listed = alice.get("/api/v1/agent/runs").json()["runs"]
    assert [item["id"] for item in listed] == [run_id]
    assert listed[0]["question"] == "알람 2023의 원인은?" and "answer_markdown" not in listed[0]


def test_unknown_or_malformed_run_ids_are_404_not_500(app_with_runner, db):
    app, _ = app_with_runner
    client = session(app, db)
    assert client.get("/api/v1/agent/runs/not-a-uuid").status_code == 404
    assert client.get("/api/v1/agent/runs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_runner_failures_are_recorded_without_leaking_exception_text(app_with_runner, db):
    app, state = app_with_runner

    async def broken(_question):
        raise RuntimeError(f"upstream said key {SECRET}")

    state["runner"] = broken
    client = session(app, db)
    run_id = start(client).json()["id"]
    detail = client.get(f"/api/v1/agent/runs/{run_id}")
    assert detail.json()["status"] == "failed" and detail.json()["error_code"] == "agent_error"
    assert SECRET not in detail.text
    stored = db.execute("SELECT row_to_json(agent_run)::text FROM agent_run").fetchone()[0]
    assert SECRET not in stored


def test_known_failures_get_specific_codes(app_with_runner, db):
    from app.agent_rag.agent import AgentOutputValidationError
    from app.agent_rag.settings import AgentNotConfigured

    app, state = app_with_runner
    client = session(app, db)

    async def invalid(_question):
        raise AgentOutputValidationError("cited a page that was not retrieved")

    async def unconfigured(_question):
        raise AgentNotConfigured("LLM_API_KEY must be configured")

    codes = []
    for runner in (invalid, unconfigured):
        state["runner"] = runner
        codes.append(client.get(f"/api/v1/agent/runs/{start(client).json()['id']}").json()["error_code"])
    assert codes == ["invalid_agent_output", "agent_not_configured"]


@pytest.mark.parametrize("question", ["", "   ", "x" * 4001])
def test_question_must_be_non_blank_and_bounded(app_with_runner, db, question):
    app, state = app_with_runner
    client = session(app, db)
    assert start(client, question).status_code == 422
    assert state["questions"] == []


def test_a_user_cannot_start_a_second_run_while_one_is_active(app_with_runner, db):
    from app.runs.service import PROCESS_ID

    app, state = app_with_runner
    client = session(app, db)
    (user_id,) = db.execute("SELECT id FROM app_user").fetchone()
    db.execute("INSERT INTO agent_run(user_id, question, status, worker_id) VALUES (%s,'busy','running',%s)",
               (user_id, PROCESS_ID))
    db.commit()
    blocked = start(client)
    assert blocked.status_code == 429 and blocked.json()["code"] == "RUN_IN_PROGRESS"
    assert state["questions"] == []


def test_runs_left_by_a_previous_process_are_reported_as_interrupted(app_with_runner, db):
    app, _ = app_with_runner
    client = session(app, db)
    (user_id,) = db.execute("SELECT id FROM app_user").fetchone()
    (run_id,) = db.execute(
        "INSERT INTO agent_run(user_id, question, status, worker_id) VALUES (%s,'old','running','previous-process') RETURNING id",
        (user_id,)).fetchone()
    db.commit()
    detail = client.get(f"/api/v1/agent/runs/{run_id}").json()
    assert detail["status"] == "failed" and detail["error_code"] == "interrupted"
    assert start(client).status_code == 202  # an orphaned run no longer blocks the user


def test_deleting_a_user_removes_their_runs_and_images(app_with_runner, db):
    app, _ = app_with_runner
    client = session(app, db)
    start(client)
    db.execute("DELETE FROM app_user")
    db.commit()
    assert db.execute("SELECT count(*) FROM agent_run").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM agent_run_asset").fetchone()[0] == 0
