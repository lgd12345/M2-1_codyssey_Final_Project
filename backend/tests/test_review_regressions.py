"""Regressions reproduced during the second review; no real model or embedding calls."""
import asyncio
from functools import partial
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest

from app.agent_rag.agent import AgentAnswer, AgentOutputValidationError, run_agent, validate_agent_output
from app.agent_rag.assets import AssetReferenceError, AssetRegistry
from app.agent_rag.preprocess import extract_query_identifiers
from app.agent_rag.retrieval import search_manual
from app.agent_rag.settings import AgentSettings
from app.agent_rag.tools import ManualAgentTools


def settings():
    return AgentSettings("https://proxy.test/v1", "test-key", "test-model", 60,
                         "postgresql://test", Path("cache"), 150)


@pytest.mark.parametrize("code", [
    "2064-01-101-01.99", "2064-01-101-01/99", "2064-01-101-01_99",
    "SM1101012035.99", "2064-01-101-01X",
])
def test_part_query_preserves_the_entire_identifier_token(code):
    found = extract_query_identifiers(f"{code}을 찾아줘")
    assert [(item.kind, item.normalized) for item in found] == [("part_no", code)]


@pytest.mark.parametrize("query", [
    "알람 번호 2023", "2023번 알람", "알람 2023.", "알람번호2023의 원인",
    "ALARM No. 2023.", "2023번 오류 코드",
])
def test_alarm_variants_remain_exact_queries(query):
    found = extract_query_identifiers(query)
    assert [(item.kind, item.normalized) for item in found] == [("alarm_number", "2023")]


def test_statement_failure_survives_real_keyword_retrieval_as_structured_status():
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise psycopg.OperationalError("private database details")

    tools = ManualAgentTools(settings())
    with patch("app.agent_rag.tools.search_manual", partial(search_manual, connection=BrokenConnection())):
        result = tools.search_manual("motor overheating")
    assert result == {"ok": False, "error": {"code": "database_unavailable"}}
    assert tools.tool_calls[-1]["error_code"] == "database_unavailable"
    assert "private" not in repr(tools.tool_calls)


def test_keyword_programming_error_is_not_mislabeled_as_database_outage():
    class InvalidQueryConnection:
        def execute(self, *_args, **_kwargs):
            raise psycopg.errors.SyntaxError("invalid internal query")

    tools = ManualAgentTools(settings())
    with patch("app.agent_rag.tools.search_manual", partial(search_manual, connection=InvalidQueryConnection())):
        with pytest.raises(psycopg.errors.SyntaxError):
            tools.search_manual("motor overheating")


def test_tool_history_records_the_arguments_the_agent_chose(monkeypatch):
    tools = ManualAgentTools(settings())
    monkeypatch.setattr("app.agent_rag.tools.search_manual", lambda *_a, **_k: {
        "results": [], "search_status": {"keyword": "no_match"}})
    monkeypatch.setattr("app.agent_rag.tools.lookup_identifier", lambda *_a, **_k: {"found": False, "matches": []})
    tools.search_manual("motor overheating", machines=["F400"], top_k=5)
    tools.lookup_identifier("X0006.3", kind="pmc_address")
    assert tools.tool_calls[0]["arguments"] == {
        "query": "motor overheating", "machines": ["F400"], "top_k": 5}
    assert tools.tool_calls[1]["arguments"] == {"value": "X0006.3", "kind": "pmc_address"}


@pytest.mark.parametrize("given,expected", [
    ("part_number", "part_no"), ("Part No", "part_no"), ("part", "part_no"),
    ("pmc", "pmc_address"), ("PMC_ADDRESS", "pmc_address"), ("alarm", "alarm_number"),
    ("alarm_number", "alarm_number"), (None, None),
    ("drawing_no", "drawing_no"), ("dwg", "drawing_no"), ("Drawing Number", "drawing_no"),
    ("drawing", "drawing_no"), ("도면번호", "drawing_no"), ("도면", "drawing_no"),
])
def test_lookup_accepts_natural_names_for_identifier_kinds(monkeypatch, given, expected):
    seen = {}
    monkeypatch.setattr("app.agent_rag.tools.lookup_identifier",
                        lambda value, kind=None, **_k: seen.update(kind=kind) or {"found": False, "matches": []})
    ManualAgentTools(settings()).lookup_identifier("2064-01-101-01", kind=given)
    assert seen["kind"] == expected


def test_unknown_identifier_kind_is_reported_instead_of_silently_not_found(monkeypatch):
    called = []
    monkeypatch.setattr("app.agent_rag.tools.lookup_identifier", lambda *a, **k: called.append(1))
    tools = ManualAgentTools(settings())
    result = tools.lookup_identifier("2064-01-101-01", kind="serial_number")
    assert result["found"] is False and result["status"] == "unknown_identifier_kind"
    assert result["valid_kinds"] == ["part_no", "drawing_no", "pmc_address", "alarm_number"]
    assert called == []
    assert tools.tool_calls[-1]["arguments"] == {"value": "2064-01-101-01", "kind": "serial_number"}


def test_search_has_no_document_type_filter():
    import inspect

    from app.agent_rag.retrieval import search_manual as retrieval_search
    # A type guessed from file names was unreliable; narrowing is by machine, which the data states.
    assert "doc_types" not in inspect.signature(ManualAgentTools.search_manual).parameters
    assert "doc_types" not in inspect.signature(retrieval_search).parameters


def test_failed_tool_calls_keep_their_arguments_too(monkeypatch):
    def broken(*_a, **_k):
        raise psycopg.OperationalError("private details")

    tools = ManualAgentTools(settings())
    monkeypatch.setattr("app.agent_rag.tools.search_manual", broken)
    tools.search_manual("motor overheating")
    assert tools.tool_calls[0]["status"] == "error"
    assert tools.tool_calls[0]["arguments"]["query"] == "motor overheating"
    assert "private" not in repr(tools.tool_calls)


def test_raw_style_block_cannot_load_external_media():
    markdown = ('<style>.page { background-image: url(https://example.test/fake.png); }</style>'
                '<div class="page">page</div>')
    with pytest.raises(AssetReferenceError):
        AssetRegistry().validate_markdown(markdown)


@pytest.mark.parametrize("markdown", [
    "```text\nsrc=PMC_X0006\n```",
    "`src=PMC_X0006`",
    "```html\n<img src=\"https://example.test/fake.png\">\n```",
    "The parameter is src=PMC_X0006.",
])
def test_image_validation_does_not_treat_literal_code_as_media(markdown):
    assert AssetRegistry().validate_markdown(markdown) == markdown


def test_answered_output_requires_evidence_even_when_no_search_was_performed():
    tools = ManualAgentTools(settings())
    with pytest.raises(AgentOutputValidationError, match="must cite retrieved"):
        validate_agent_output(AgentAnswer(status="answered", answer_markdown="The pump is broken."), tools)


def test_insufficient_evidence_output_does_not_require_irrelevant_citations():
    tools = ManualAgentTools(settings())
    tools.available_citations[("a" * 64, 1)] = {
        "document_sha256": "a" * 64, "page": 1, "title": "Unrelated manual", "printed_page": None,
    }
    result = validate_agent_output(AgentAnswer(
        status="insufficient_evidence", answer_markdown="The manual does not establish an answer."
    ), tools)
    assert result.to_dict()["status"] == "insufficient_evidence"
    assert result.citations == ()


def test_agent_can_complete_more_than_fifty_model_requests():
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    count = 0

    def model_function(_messages, info):
        nonlocal count
        count += 1
        if count <= 51:
            return ModelResponse(parts=[ToolCallPart("lookup_identifier", {"value": "X0006.3"})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "status": "insufficient_evidence", "answer_markdown": "No matching source.",
            "citations": [], "asset_ids": [],
        })])

    with patch("app.agent_rag.tools.lookup_identifier", return_value={"found": False, "matches": []}):
        result = asyncio.run(run_agent("Investigate", settings=settings(), model=FunctionModel(model_function)))
    assert count == 52
    assert len(result.tool_calls) == 51
    assert result.status == "insufficient_evidence"


def test_search_open_image_and_final_citation_round_trip(monkeypatch):
    import io

    from PIL import Image
    from pydantic_ai import BinaryContent
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel

    from app.agent_rag.pdf_source import SourcePage

    digest = "d" * 64
    tools = ManualAgentTools(settings())
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(output, format="PNG")
    png = output.getvalue()
    source = {"document_sha256": digest, "pdf_page": 3, "title": "Manual",
              "printed_page": "12", "verification": "needs_review"}
    monkeypatch.setattr("app.agent_rag.tools.search_manual", lambda *_a, **_kw: {
        "results": [{"sources": [source], "content": "converted text"}],
        "search_status": {"keyword": "ok"},
    })

    def fake_open(_digest, page, *, asset_registry, **_kwargs):
        asset_id = asset_registry.register(png, document_sha256=digest, pdf_page=page)
        return SourcePage(digest, page, "12", "Manual", "converted text", "needs_review",
                          "text", "PDF text layer", png, asset_id)

    monkeypatch.setattr("app.agent_rag.tools.open_source_page", fake_open)
    count = 0

    def model_function(messages, info):
        nonlocal count
        count += 1
        if count == 1:
            return ModelResponse(parts=[ToolCallPart("search_manual", {"query": "motor"})])
        if count == 2:
            return ModelResponse(parts=[ToolCallPart("open_source", {"doc_sha256": digest, "pdf_page": 3})])
        image_parts = [item for message in messages for part in message.parts
                       if isinstance(part, UserPromptPart) and isinstance(part.content, (list, tuple))
                       for item in part.content if isinstance(item, BinaryContent)]
        assert any(item.data == png for item in image_parts)
        asset_id = tools.assets.all()[0].asset_id
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "status": "answered", "answer_markdown": f"Confirmed source ![](asset:{asset_id})",
            "citations": [{"document_sha256": digest, "page": 3, "title": "Manual", "printed_page": "12"}],
            "asset_ids": [asset_id],
        })])

    result = asyncio.run(run_agent("Inspect the manual", settings=settings(), tools=tools,
                                   model=FunctionModel(model_function)))
    assert [call["tool"] for call in result.tool_calls] == ["search_manual", "open_source"]
    assert result.citations[0]["page"] == 3
    assert result.assets[0].data == png
    assert result.status == "answered"
