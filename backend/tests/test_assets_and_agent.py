import asyncio

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.agent_rag.agent import (
    AgentAnswer,
    AgentOutputValidationError,
    Citation,
    SYSTEM_INSTRUCTIONS,
    build_agent,
    validate_agent_output,
)
from app.agent_rag.assets import AssetRegistry, AssetReferenceError
from app.agent_rag.settings import AgentSettings
from app.agent_rag.tools import ManualAgentTools
from app.agent_rag.pdf_source import SourcePage


def test_agent_explains_text_is_converted_and_may_be_wrong():
    assert "변환 텍스트" in SYSTEM_INSTRUCTIONS
    assert "OCR" in SYSTEM_INSTRUCTIONS
    assert "PDF 텍스트 레이어 추출" in SYSTEM_INSTRUCTIONS
    assert "needs_review" in SYSTEM_INSTRUCTIONS
    assert "open_source" in SYSTEM_INSTRUCTIONS
    assert "OCR 결과" not in SYSTEM_INSTRUCTIONS


def test_only_images_opened_in_current_run_can_be_referenced():
    registry = AssetRegistry()
    asset_id = registry.register(b"png-bytes", document_sha256="a" * 64, pdf_page=3)
    assert registry.validate_markdown(f"참고 ![](asset:{asset_id})") == f"참고 ![](asset:{asset_id})"
    with pytest.raises(AssetReferenceError):
        registry.validate_markdown("![](asset:not-opened)")
    with pytest.raises(AssetReferenceError):
        registry.validate_markdown("![](https://example.test/fake.png)")


@pytest.mark.parametrize("markdown", [
    '<img src="https://example.test/fake.png">',
    '<div style="background-image: url(https://example.test/fake.png)"></div>',
    "![figure][source]\n\n[source]: https://example.test/fake.png",
    "![shortcut]\n\n[shortcut]: https://example.test/fake.png",
])
def test_only_inline_opened_asset_markdown_is_allowed(markdown):
    with pytest.raises(AssetReferenceError):
        AssetRegistry().validate_markdown(markdown)


def test_agent_output_citations_and_assets_must_be_grounded_in_tool_results():
    settings = AgentSettings("", "", "", 60, "", __import__("pathlib").Path("cache"), 150)
    tools = ManualAgentTools(settings)
    digest = "c" * 64
    tools.available_citations[(digest, 2)] = {
        "document_sha256": digest, "page": 2, "printed_page": "PL-4", "title": "Parts list"
    }
    asset = tools.assets.register(b"png", document_sha256=digest, pdf_page=2)
    answer = AgentAnswer(status="answered", answer_markdown=f"![](asset:{asset})", citations=[
        Citation(document_sha256=digest, page=2, printed_page="PL-4", title="Parts list")
    ], asset_ids=[asset])
    result = validate_agent_output(answer, tools)
    assert result.to_dict()["citations"][0]["page"] == 2
    with pytest.raises(AgentOutputValidationError, match="must cite retrieved"):
        validate_agent_output(AgentAnswer(status="answered", answer_markdown="펌프 고장입니다."), tools)
    assert result.to_dict()["assets"][0]["asset_id"] == asset
    with pytest.raises(AgentOutputValidationError, match="not retrieved or opened"):
        validate_agent_output(AgentAnswer(status="answered", answer_markdown="근거", citations=[
            Citation(document_sha256="d" * 64, page=99, title="fake")
        ]), tools)


def test_open_source_tool_returns_image_content_and_registers_the_asset(monkeypatch):
    settings = AgentSettings("", "", "", 60, "postgresql://test", __import__("pathlib").Path("cache"), 150)
    tools = ManualAgentTools(settings)
    image_bytes = b"\\x89PNG\\r\\nsource-page"

    def fake_open(_digest, page, *, asset_registry, **_kwargs):
        asset_id = asset_registry.register(image_bytes, document_sha256="e" * 64, pdf_page=page)
        return SourcePage("e" * 64, page, "PL-4", "Parts manual", "converted table",
                          "needs_review", "table", "PDF text", image_bytes, asset_id)

    monkeypatch.setattr("app.agent_rag.tools.open_source_page", fake_open)
    tool_result = tools.open_source("e" * 64, 4)
    assert tool_result.return_value["text_origin"] == "original_pdf_rendered"
    assert tool_result.return_value["converted_text_origin"] == "ocr_or_text_extraction"
    assert tool_result.return_value["asset_id"] in {asset.asset_id for asset in tools.assets.all()}
    assert tool_result.content[0].data == image_bytes
    assert tools.tool_calls[-1]["tool"] == "open_source"


def test_prompt_defines_all_three_answer_statuses():
    for status in ("answered", "insufficient_evidence", "conversational"):
        assert status in SYSTEM_INSTRUCTIONS


def test_conversational_output_needs_no_citation_but_is_reported_as_such():
    settings = AgentSettings("", "", "", 60, "", __import__("pathlib").Path("cache"), 150)
    result = validate_agent_output(AgentAnswer(status="conversational", answer_markdown="안녕하세요!"),
                                   ManualAgentTools(settings))
    assert result.to_dict()["status"] == "conversational" and result.citations == ()


def test_agent_has_no_default_model_request_limit(monkeypatch):
    from app.agent_rag.agent import run_agent

    settings = AgentSettings("https://proxy.test/v1", "test-key", "test-model", 60,
                             "postgresql://test", __import__("pathlib").Path("cache"), 150)
    model = TestModel(call_tools=[], custom_output_args={
        "status": "insufficient_evidence", "answer_markdown": "확인된 근거가 없습니다.",
        "citations": [], "asset_ids": []
    })
    original_run = Agent.run
    observed = {}

    async def record_limits(self, *args, **kwargs):
        observed["limits"] = kwargs.get("usage_limits")
        return await original_run(self, *args, **kwargs)

    monkeypatch.setattr(Agent, "run", record_limits)
    asyncio.run(run_agent("테스트 질문", settings=settings, model=model))
    assert observed["limits"].request_limit is None


def test_tools_return_structured_operational_failures(monkeypatch):
    import psycopg

    settings = AgentSettings("", "", "", 60, "postgresql://test", __import__("pathlib").Path("cache"), 150)
    tools = ManualAgentTools(settings)
    monkeypatch.setattr("app.agent_rag.tools.search_manual", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(psycopg.OperationalError("private db details")))
    search_error = tools.search_manual("question")
    assert search_error == {"ok": False, "error": {"code": "database_unavailable"}}
    assert tools.tool_calls[-1]["status"] == "error"
    failed_run = validate_agent_output(AgentAnswer(
        status="insufficient_evidence", answer_markdown="검색 상태 확인"
    ), tools).to_dict()
    assert failed_run["retrieval_status"] == [{"status": "error", "code": "database_unavailable"}]

    monkeypatch.setattr("app.agent_rag.tools.lookup_identifier", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(psycopg.OperationalError("private db details")))
    lookup_error = tools.lookup_identifier("X0006.3")
    assert lookup_error == {"ok": False, "error": {"code": "database_unavailable"}}

    monkeypatch.setattr("app.agent_rag.tools.open_source_page", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(FileNotFoundError("private file path")))
    source_error = tools.open_source("e" * 64, 4)
    assert source_error.return_value == {"ok": False, "error": {"code": "source_missing"}}
    assert "private" not in repr(tools.tool_calls)


def test_test_model_performs_a_real_tool_round_trip_and_validates_citation():
    from app.agent_rag.agent import run_agent

    settings = AgentSettings("https://proxy.test/v1", "test-key", "test-model", 60,
                             "postgresql://test", __import__("pathlib").Path("cache"), 150)
    tools = ManualAgentTools(settings)
    digest = "f" * 64
    called = []

    def fake_lookup(value: str, kind: str | None = None):
        called.append((value, kind))
        citation = {"document_sha256": digest, "page": 7, "printed_page": "12", "title": "Manual"}
        tools.available_citations[(digest, 7)] = citation
        tools.tool_calls.append({"tool": "lookup_identifier", "status": "ok", "found": True})
        return {"found": True, "value": value, "matches": [citation]}

    fake_lookup.__name__ = "lookup_identifier"
    tools.lookup_identifier = fake_lookup
    model = TestModel(call_tools=["lookup_identifier"], custom_output_args={
        "status": "answered", "answer_markdown": "확인된 출처입니다.",
        "citations": [{"document_sha256": digest, "page": 7, "printed_page": "12", "title": "Manual"}],
        "asset_ids": [],
    })
    result = asyncio.run(run_agent("PMC 주소를 찾아줘", settings=settings, tools=tools, model=model))
    assert called
    assert result.citations[0]["page"] == 7
    assert result.tool_calls[0]["tool"] == "lookup_identifier"


def test_agent_database_can_be_safely_overridden_from_application_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://host/app")
    monkeypatch.setenv("RAG_DATABASE_URL", "postgresql://host/app_test")
    assert AgentSettings.from_env().database_url == "postgresql://host/app_test"


def test_agent_requires_explicit_llm_proxy_and_key_configuration():
    settings = AgentSettings("https://proxy.test/v1", "", "model", 60,
                             "postgresql://test", __import__("pathlib").Path("cache"), 150)
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        settings.validate_llm()


def test_pydantic_agent_runs_without_network_and_has_tools_registered():
    settings = AgentSettings("https://proxy.test/v1", "test-key", "test-model", 60,
                             "postgresql://test", __import__("pathlib").Path("cache"), 150)
    tools = ManualAgentTools(settings)
    model = TestModel(call_tools=[], custom_output_args={
        "status": "insufficient_evidence", "answer_markdown": "확인된 근거가 없습니다.",
        "citations": [], "asset_ids": []
    })
    agent, _ = build_agent(settings, tools=tools, model=model)
    result = asyncio.run(agent.run("테스트 질문"))
    assert result.output.answer_markdown == "확인된 근거가 없습니다."
    assert set(agent._function_toolset.tools) == {"search_manual", "lookup_identifier", "open_source"}
