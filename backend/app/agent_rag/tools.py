from __future__ import annotations

from typing import Any, Sequence

import psycopg
from pydantic_ai import BinaryContent, ToolReturn

from app.agent_rag.assets import AssetRegistry
from app.agent_rag.case_retrieval import search_cases
from app.agent_rag.embedding import GeminiEmbedder
from app.agent_rag.pdf_source import open_source_page
from app.agent_rag.retrieval import lookup_identifier, search_manual
from app.agent_rag.settings import AgentSettings
from app.agent_rag.tables import table_evidence


VALID_KINDS = ["part_no", "drawing_no", "pmc_address", "alarm_number"]
_KIND_ALIASES = {
    "part_no": "part_no", "partno": "part_no", "part_number": "part_no", "part": "part_no", "partnumber": "part_no",
    "drawing_no": "drawing_no", "drawingno": "drawing_no", "drawing_number": "drawing_no", "drawing": "drawing_no",
    "dwg": "drawing_no", "dwg_no": "drawing_no", "drawingnumber": "drawing_no", "도면": "drawing_no", "도면번호": "drawing_no",
    "pmc_address": "pmc_address", "pmc": "pmc_address", "pmcaddress": "pmc_address", "address": "pmc_address",
    "alarm_number": "alarm_number", "alarm": "alarm_number", "alarmnumber": "alarm_number",
    "alarm_no": "alarm_number", "alarm_code": "alarm_number",
}


def normalize_kind(kind: str | None) -> str | None:
    """Map the names a model naturally uses to stored kinds. Unknown names return the sentinel '?'."""
    if kind is None or not kind.strip():
        return None
    key = kind.strip().casefold().replace(" ", "_").replace("-", "_")
    return _KIND_ALIASES.get(key) or _KIND_ALIASES.get(key.replace("_", ""), "?")


class ManualAgentTools:
    """Bounded-to-the-manual-corpus tools. No arbitrary SQL, HTTP self-calls or agent-call budget."""

    def __init__(self, settings: AgentSettings, *, embedder: GeminiEmbedder | None = None):
        self.settings = settings
        self.embedder = embedder
        self.assets = AssetRegistry()
        self.available_citations: dict[tuple[str, int], dict[str, Any]] = {}
        self.available_cases: dict[str, dict[str, Any]] = {}
        self.tool_calls: list[dict[str, Any]] = []

    def _remember(self, source: dict[str, Any]) -> None:
        digest = source.get("document_sha256")
        page = source.get("pdf_page")
        if digest and page:
            self.available_citations[(str(digest), int(page))] = {
                "document_sha256": str(digest), "page": int(page),
                "printed_page": source.get("printed_page"), "title": str(source.get("title", "")),
            }

    def _failure(self, tool: str, code: str, **details: Any) -> dict[str, Any]:
        call = {"tool": tool, "status": "error", "error_code": code}
        call.update(details)
        self.tool_calls.append(call)
        return {"ok": False, "error": {"code": code}}

    def search_manual(self, query: str, machines: list[str] | None = None, top_k: int = 8) -> dict[str, Any]:
        """Search converted manual pages by exact identifier, Korean/English keywords and semantic vector."""
        arguments = {"query": query, "machines": machines, "top_k": top_k}
        try:
            result = search_manual(query, machines=machines, top_k=top_k,
                                   embedder=self.embedder, database_url=self.settings.database_url)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            return self._failure("search_manual", "database_unavailable", arguments=arguments)
        for candidate in result["results"]:
            for source in candidate["sources"]:
                self._remember(source)
        self.tool_calls.append({"tool": "search_manual", "status": "ok", "arguments": arguments,
                                "result_count": len(result["results"]),
                                "search_status": result["search_status"]})
        return result

    def search_cases(self, query: str, machines: list[str] | None = None, top_k: int = 6) -> dict[str, Any]:
        """Search past service cases (FSR): similar complaints with the resolution that was actually applied.

        machines is optional and filters by the case machine code (e.g. VMCT-02); leave it empty when unsure.
        """
        arguments = {"query": query, "machines": machines, "top_k": top_k}
        try:
            result = search_cases(query, machines=machines, top_k=top_k,
                                  embedder=self.embedder, database_url=self.settings.database_url)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            return self._failure("search_cases", "database_unavailable", arguments=arguments)
        for case in result["results"]:
            self.available_cases[case["fsr_no"]] = {"fsr_no": case["fsr_no"], "machine": case["machine"],
                                                    "registered_on": case["registered_on"]}
        self.tool_calls.append({"tool": "search_cases", "status": "ok", "arguments": arguments,
                                "result_count": len(result["results"]),
                                "fsr_nos": [case["fsr_no"] for case in result["results"]],
                                "search_status": result["search_status"]})
        return result

    def lookup_identifier(self, value: str, kind: str | None = None) -> dict[str, Any]:
        """Look up a machine alarm number, PMC address or part number using exact matching only.

        kind is optional; when given it must be one of: part_no, drawing_no, pmc_address, alarm_number.
        part_no and drawing_no are the same family of code, so either finds both.
        """
        arguments = {"value": value, "kind": kind}
        resolved = normalize_kind(kind)
        if resolved == "?":
            self.tool_calls.append({"tool": "lookup_identifier", "status": "error", "arguments": arguments,
                                    "error_code": "unknown_identifier_kind"})
            return {"found": False, "matches": [], "status": "unknown_identifier_kind", "valid_kinds": VALID_KINDS}
        try:
            result = lookup_identifier(value, kind=resolved, database_url=self.settings.database_url)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            return self._failure("lookup_identifier", "database_unavailable", arguments=arguments)
        for source in result["matches"]:
            self._remember(source)
        self.tool_calls.append({"tool": "lookup_identifier", "status": "ok", "arguments": arguments,
                                "found": result["found"],
                                "match_count": len(result["matches"])})
        return result

    def open_source(self, doc_sha256: str, pdf_page: int) -> ToolReturn:
        """Open one original PDF page; returns the rendered image, PDF text layer and converted text."""
        try:
            page = open_source_page(doc_sha256, pdf_page, asset_registry=self.assets,
                                    database_url=self.settings.database_url,
                                    dpi=self.settings.pdf_render_dpi)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            return ToolReturn(return_value=self._failure("open_source", "database_unavailable"))
        except FileNotFoundError:
            return ToolReturn(return_value=self._failure("open_source", "source_missing",
                                                         document_sha256=doc_sha256, pdf_page=pdf_page))
        except LookupError:
            return ToolReturn(return_value=self._failure("open_source", "page_not_found",
                                                         document_sha256=doc_sha256, pdf_page=pdf_page))
        except ValueError:
            return ToolReturn(return_value=self._failure("open_source", "source_integrity_error",
                                                         document_sha256=doc_sha256, pdf_page=pdf_page))
        except (OSError, RuntimeError):
            return ToolReturn(return_value=self._failure("open_source", "source_render_failed",
                                                         document_sha256=doc_sha256, pdf_page=pdf_page))
        citation = {"document_sha256": page.document_sha256, "page": page.pdf_page,
                    "printed_page": page.printed_page, "title": page.title}
        self.available_citations[(page.document_sha256, page.pdf_page)] = citation
        self.tool_calls.append({"tool": "open_source", "document_sha256": page.document_sha256,
                                "pdf_page": page.pdf_page, "verification": page.verification})
        return ToolReturn(
            return_value={"document_sha256": page.document_sha256, "title": page.title,
                          "pdf_page": page.pdf_page, "printed_page": page.printed_page,
                          "page_class": page.page_class, "text_origin": "original_pdf_rendered",
                          "converted_text_origin": "ocr_or_text_extraction", "verification": page.verification, "converted_text": page.converted_text,
                          "table_evidence": table_evidence(page.converted_text),
                          "pdf_text_layer": page.pdf_text, "asset_id": page.asset_id,
                          "image_media_type": "image/png"},
            content=[BinaryContent(data=page.image_png, media_type="image/png")],
        )
