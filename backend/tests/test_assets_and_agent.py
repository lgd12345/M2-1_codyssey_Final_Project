import pytest

from app.agent_rag.assets import AssetRegistry, AssetReferenceError
from app.agent_rag.settings import AgentSettings
from app.agent_rag.tools import ManualAgentTools
from app.agent_rag.pdf_source import SourcePage


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


def test_tools_return_structured_operational_failures(monkeypatch):
    import psycopg

    settings = AgentSettings("", "", "", 60, "postgresql://test", __import__("pathlib").Path("cache"), 150)
    tools = ManualAgentTools(settings)
    monkeypatch.setattr("app.agent_rag.tools.search_manual", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(psycopg.OperationalError("private db details")))
    search_error = tools.search_manual("question")
    assert search_error == {"ok": False, "error": {"code": "database_unavailable"}}
    assert tools.tool_calls[-1]["status"] == "error"

    monkeypatch.setattr("app.agent_rag.tools.lookup_identifier", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(psycopg.OperationalError("private db details")))
    lookup_error = tools.lookup_identifier("X0006.3")
    assert lookup_error == {"ok": False, "error": {"code": "database_unavailable"}}

    monkeypatch.setattr("app.agent_rag.tools.open_source_page", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(FileNotFoundError("private file path")))
    source_error = tools.open_source("e" * 64, 4)
    assert source_error.return_value == {"ok": False, "error": {"code": "source_missing"}}
    assert "private" not in repr(tools.tool_calls)


def test_agent_requires_explicit_llm_proxy_and_key_configuration():
    settings = AgentSettings("https://proxy.test/v1", "", "model", 60,
                             "postgresql://test", __import__("pathlib").Path("cache"), 150)
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        settings.validate_llm()
