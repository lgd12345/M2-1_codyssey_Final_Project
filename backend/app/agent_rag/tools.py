from __future__ import annotations

import json
from typing import Any, Sequence

import psycopg
from pydantic_ai import BinaryContent, ToolReturn

from app.agent_rag.assets import AssetRegistry
from app.agent_rag.case_retrieval import search_cases
from app.agent_rag.context import ContextPolicy, compact_cases, compact_identifier, compact_manual, compact_source
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

    def __init__(self, settings: AgentSettings, *, embedder: GeminiEmbedder | None = None,
                 policy: ContextPolicy | None = None):
        """With a policy, results are returned as compact views and calls are budgeted (service analysis).

        Without one the tools behave as before. Citation validation always uses the raw results either way.
        """
        self.settings = settings
        self.embedder = embedder
        self.policy = policy
        self._served: set[tuple[str, str]] = set()
        self._executed = 0
        self._opened = 0
        self.assets = AssetRegistry()
        self.available_citations: dict[tuple[str, int], dict[str, Any]] = {}
        self.available_cases: dict[str, dict[str, Any]] = {}
        self.tool_calls: list[dict[str, Any]] = []

    def _remember(self, source: dict[str, Any], *, match_type: str | None = None,
                  matched_identifiers: list[dict[str, str]] | None = None) -> None:
        digest = source.get("document_sha256")
        page = source.get("pdf_page") or source.get("page")
        if digest and page:
            key = (str(digest), int(page))
            previous = self.available_citations.get(key, {})
            citation = {**previous, "document_sha256": str(digest), "page": int(page),
                        "printed_page": source.get("printed_page") or previous.get("printed_page"),
                        "title": str(source.get("title") or previous.get("title", ""))}
            matched = [*previous.get('matched_identifiers', []), *(matched_identifiers or [])]
            if source.get('kind') and source.get('normalized'):  # lookup_identifier is itself exact-only
                matched.append({'kind': source['kind'], 'value': source['normalized']})
            if matched:
                citation['matched_identifiers'] = list({(item['kind'], item['value']): item for item in matched}.values())
            if match_type:
                citation['retrieval_types'] = list(dict.fromkeys([*previous.get('retrieval_types', []), match_type]))
            self.available_citations[key] = citation

    @staticmethod
    def _call_key(tool: str, arguments: dict[str, Any]) -> tuple[str, str]:
        def normal(value: Any) -> Any:
            return ' '.join(value.split()).casefold() if isinstance(value, str) else value
        return tool, json.dumps({key: normal(value) for key, value in arguments.items()}, sort_keys=True, ensure_ascii=False)

    def _gate(self, tool: str, arguments: dict[str, Any], *, opens: bool = False) -> dict[str, Any] | None:
        """Short-circuit repeats and calls over budget so neither re-sends context or reaches the database."""
        if self.policy is None:
            return None
        if self._call_key(tool, arguments) in self._served:
            return {"ok": True, "repeat": True, "note": "동일한 호출을 이미 했습니다. 앞선 결과를 사용하세요."}
        if self._executed >= self.policy.max_tool_calls or (opens and self._opened >= self.policy.max_open_source):
            self.tool_calls.append({"tool": tool, "status": "error", "error_code": "tool_budget_exhausted"})
            return {"ok": False, "error": {"code": "tool_budget_exhausted"},
                    "note": "도구 호출 한도에 도달했습니다. 지금까지 확보한 근거만으로 답을 정리하세요."}
        self._executed += 1
        self._opened += int(opens)
        return None

    def _served_ok(self, tool: str, arguments: dict[str, Any]) -> None:
        self._served.add(self._call_key(tool, arguments))  # only successes: a failed call may be retried

    def _failure(self, tool: str, code: str, **details: Any) -> dict[str, Any]:
        call = {"tool": tool, "status": "error", "error_code": code}
        call.update(details)
        self.tool_calls.append(call)
        return {"ok": False, "error": {"code": code}}

    def search_manual(self, query: str, machines: list[str] | None = None, top_k: int = 8) -> dict[str, Any]:
        """Search converted manual pages by exact identifier, Korean/English keywords and semantic vector."""
        arguments = {"query": query, "machines": machines, "top_k": top_k}
        if (blocked := self._gate("search_manual", arguments)) is not None:
            return blocked
        try:
            result = search_manual(query, machines=machines, top_k=top_k,
                                   embedder=self.embedder, database_url=self.settings.database_url)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            return self._failure("search_manual", "database_unavailable", arguments=arguments)
        for candidate in result["results"]:
            for source in candidate["sources"]:
                self._remember(source, match_type=candidate.get('match_type'),
                               matched_identifiers=candidate.get('matched_identifiers'))
        self.tool_calls.append({"tool": "search_manual", "status": "ok", "arguments": arguments,
                                "result_count": len(result["results"]),
                                "search_status": result["search_status"]})
        self._served_ok("search_manual", arguments)
        return compact_manual(result, query, self.policy) if self.policy else result

    def search_cases(self, query: str, machines: list[str] | None = None, top_k: int = 6) -> dict[str, Any]:
        """Search past service cases (FSR): similar complaints with the resolution that was actually applied.

        machines is optional and filters by the case machine code (e.g. VMCT-02); leave it empty when unsure.
        """
        arguments = {"query": query, "machines": machines, "top_k": top_k}
        if (blocked := self._gate("search_cases", arguments)) is not None:
            return blocked
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
        self._served_ok("search_cases", arguments)
        return compact_cases(result, self.policy) if self.policy else result

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
        if (blocked := self._gate("lookup_identifier", arguments)) is not None:
            return blocked
        try:
            result = lookup_identifier(value, kind=resolved, database_url=self.settings.database_url)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            return self._failure("lookup_identifier", "database_unavailable", arguments=arguments)
        for source in result["matches"]:
            self._remember(source)
        self.tool_calls.append({"tool": "lookup_identifier", "status": "ok", "arguments": arguments,
                                "found": result["found"],
                                "match_count": len(result["matches"])})
        self._served_ok("lookup_identifier", arguments)
        return compact_identifier(result, value, self.policy) if self.policy else result

    def open_source(self, doc_sha256: str, pdf_page: int) -> ToolReturn:
        """Open one original PDF page; returns the rendered image, PDF text layer and converted text."""
        arguments = {"doc_sha256": doc_sha256, "pdf_page": pdf_page}
        if (blocked := self._gate("open_source", arguments, opens=True)) is not None:
            return ToolReturn(return_value=blocked)
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
        self._remember(citation)  # opening an image must not erase the search evidence classification
        self.tool_calls.append({"tool": "open_source", "document_sha256": page.document_sha256,
                                "pdf_page": page.pdf_page, "verification": page.verification})
        self._served_ok("open_source", arguments)
        full = {"document_sha256": page.document_sha256, "title": page.title,
                          "pdf_page": page.pdf_page, "printed_page": page.printed_page,
                          "page_class": page.page_class, "text_origin": "original_pdf_rendered",
                          "converted_text_origin": "ocr_or_text_extraction", "verification": page.verification, "converted_text": page.converted_text,
                          "table_evidence": table_evidence(page.converted_text),
                          "pdf_text_layer": page.pdf_text, "asset_id": page.asset_id,
                          "image_media_type": "image/png"}
        return ToolReturn(return_value=compact_source(full, self.policy) if self.policy else full,
                          content=[BinaryContent(data=page.image_png, media_type="image/png")])
