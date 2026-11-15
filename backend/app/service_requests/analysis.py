"""Analysis lifecycle for stored requests: begin -> (model runner) -> validated, durable result.

Starting an analysis is what makes a request 처리 중. It never creates department work: the analysis is an operator aid.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.auth.service import AuthError

PROCESS_ID = uuid4().hex  # a running row owned by another process was orphaned by a restart
DEPARTMENT_KEYS = ('service', 'quality', 'parts', 'sales')
NO_RECOMMENDATION = 'AI가 이 요청에 필요한 부서로 추천하지 않았습니다.'
AnalysisRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class AnalysisInProgress(AuthError):
    status_code, code = 409, 'ANALYSIS_IN_PROGRESS'
    message = '이미 분석이 진행 중입니다.'


class AnalysisNotAllowed(AuthError):
    status_code, code = 409, 'ANALYSIS_NOT_ALLOWED'
    message = '이 요청은 지금 분석을 시작할 수 없습니다. 이미 분석했거나 종결된 요청입니다.'


class AnalysisRequestNotFound(AuthError):
    status_code, code = 404, 'REQUEST_NOT_FOUND'
    message = '요청 또는 장비를 찾을 수 없습니다.'


def get_analysis_runner() -> AnalysisRunner:
    """Dependency seam: tests replace this so no real model is called."""
    from app.service_requests.analyzer import analyze_request
    return analyze_request


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class EvidenceRef(_Model):
    """Where a manual citation lives in the indexed corpus. Only the server uses it, to render the original page."""
    document_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    page: int = Field(ge=1, le=100000)


class Evidence(_Model):
    id: str = Field(min_length=1, max_length=20)
    kind: Literal['fsr', 'manual']
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    excerpt: str
    note: str
    ref: EvidenceRef | None = None

    @model_validator(mode='after')
    def only_manuals_have_pages(self):
        if self.ref is not None and self.kind != 'manual':
            raise ValueError('only a manual citation can reference a page')
        return self


class Cause(_Model):
    title: str = Field(min_length=1)
    level: Literal['높음', '중간', '낮음']
    detail: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)


class Part(_Model):
    name: str = Field(min_length=1)
    note: str
    source: str = Field(min_length=1)


class Recommendation(_Model):
    key: Literal['service', 'quality', 'parts', 'sales']
    reason: str = Field(min_length=1)
    draft: str = Field(min_length=1)


class IdentifierCheck(_Model):
    """Outcome of the server's exact lookup of one identifier. 'not_found' means absent from the indexed manuals."""
    kind: str = Field(min_length=1)
    value: str = Field(min_length=1)
    status: Literal['found', 'not_found', 'check_failed']
    source: Literal['server', 'agent']


class AnalysisResult(_Model):
    status: Literal['answered', 'insufficient_evidence']
    summary: str = Field(min_length=1)
    causes: list[Cause] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    parts: list[Part] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    departments: list[Recommendation] = Field(default_factory=list)
    case_search: Literal['ok', 'unavailable'] = 'ok'
    identifier_checks: list[IdentifierCheck] = Field(default_factory=list)

    @field_validator('departments')
    @classmethod
    def unique_departments(cls, values):
        keys = [value.key for value in values]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate department')
        return values

    @model_validator(mode='after')
    def consistent(self):
        ids = [item.id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate evidence id')
        for cause in self.causes:
            if not set(cause.evidence) <= set(ids):
                raise ValueError('cause references unknown evidence')
        if self.status == 'answered' and not self.evidence:
            raise ValueError('an answered analysis needs retrieved evidence')
        if self.status == 'insufficient_evidence' and (self.causes or self.parts or self.departments or self.evidence):
            raise ValueError('insufficient evidence cannot carry conclusions or recommendations')
        return self


def validate_result(raw: Any) -> dict[str, Any]:
    result = AnalysisResult.model_validate(raw).model_dump(mode='json')
    for evidence in result['evidence']:
        if evidence['ref'] is None:
            del evidence['ref']  # absent rather than null: citations without a page look exactly as before
    return result


class InvalidAnalysis(ValueError):
    pass


def error_code_for(error: BaseException) -> str:
    """Map an exception to a stable public code. The exception text is never stored."""
    from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
    from app.agent_rag.settings import AgentNotConfigured

    if isinstance(error, (ValidationError, InvalidAnalysis)):
        return 'invalid_analysis'
    if isinstance(error, ModelAPIError):  # connection, timeout, HTTP status, rate limit, quota: the model is not usable now
        return 'llm_unavailable'
    if isinstance(error, UnexpectedModelBehavior):
        return 'invalid_agent_output'
    if isinstance(error, AgentNotConfigured):
        return 'agent_not_configured'
    try:
        import openai
        if isinstance(error, openai.APIError):
            return 'llm_unavailable'
    except ImportError:  # pragma: no cover - openai ships with pydantic-ai[openai]
        pass
    if isinstance(error, psycopg.Error):
        return 'database_unavailable'
    return 'agent_error'


def recover_orphans(connection) -> None:
    """A run owned by another process was cut off by a restart: it failed, and the request stays 처리 중."""
    with connection.transaction():
        connection.execute("UPDATE service_analysis SET status='failed', error_code='interrupted', finished_at=now() "
                           "WHERE status='running' AND worker_id <> %s", (PROCESS_ID,))


def add_history(connection, number: int, text: str, public_text: str | None = None) -> None:
    connection.execute('INSERT INTO service_history(request_id,text,public_text) VALUES (%s,%s,%s)',
                       (number, text, public_text))


def begin(connection, number: int, user_id: UUID, *, first: bool = True,
          history: str | None = None) -> tuple[UUID, dict[str, Any], bool]:
    """Atomically claim a request for analysis and return the stored facts the model may use.

    first=True is the first analysis (a failed attempt may be retried): it needs a request with no successful analysis.
    first=False is a re-analysis of a request that is already 처리 중. The last value says whether this call moved the
    request from 접수됨 to 처리 중 (the moment customers are told processing has started).
    """
    recover_orphans(connection)
    with connection.transaction():
        row = connection.execute(
            'SELECT status,message,reason,alarm_numbers,equipment_snapshot FROM service_request WHERE id=%s FOR UPDATE',
            (number,)).fetchone()
        if row is None:
            raise AnalysisRequestNotFound()
        if connection.execute("SELECT 1 FROM service_analysis WHERE request_id=%s AND status='running'", (number,)).fetchone():
            raise AnalysisInProgress()
        allowed = ('접수됨', '처리 중') if first else ('처리 중',)
        if row[0] not in allowed or (first and connection.execute(
                "SELECT 1 FROM service_analysis WHERE request_id=%s AND status='succeeded'", (number,)).fetchone()):
            raise AnalysisNotAllowed()
        analysis_id = connection.execute(
            'INSERT INTO service_analysis(request_id,requested_by,worker_id,previous_status) VALUES (%s,%s,%s,%s) RETURNING id',
            (number, user_id, PROCESS_ID, row[0])).fetchone()[0]
        started = row[0] == '접수됨'
        if started:
            connection.execute("UPDATE service_request SET status='처리 중' WHERE id=%s", (number,))
            add_history(connection, number, '처리 시작 · 분석 시작', '처리를 시작했습니다.')
        if history:
            add_history(connection, number, history)
        notes = [note[0] for note in connection.execute(
            'SELECT text FROM service_additional_info WHERE request_id=%s ORDER BY created_at,id', (number,)).fetchall()]
    snapshot = row[4]
    # Only diagnostic facts: the customer's contact details are deliberately not sent to a model.
    return analysis_id, {'message': row[1], 'reason': row[2], 'alarm_numbers': list(row[3]),
                         'machine': snapshot['machine'], 'additional_info': notes}, started


def finish_success(connection, analysis_id: UUID, result: dict[str, Any]) -> None:
    with connection.transaction():
        row = connection.execute(
            """UPDATE service_analysis SET status='succeeded', result=%s, finished_at=now()
               WHERE id=%s AND status='running' RETURNING request_id""",
            (Jsonb(result, dumps=lambda item: json.dumps(item, ensure_ascii=False)), analysis_id)).fetchone()
        if not row:
            return
        number = row[0]
        # Recommended mail activities are projected directly from this saved analysis result.
        insufficient = result['status'] == 'insufficient_evidence'
        connection.execute("UPDATE service_request SET revision=(SELECT count(*) FROM service_analysis WHERE request_id=%s AND status='succeeded') "
                           "WHERE id=%s", (number, number))
        add_history(connection, number, '분석 완료 · 근거 부족, 확인 필요' if insufficient else '분석 완료')


def finish_failure(connection, analysis_id: UUID, code: str) -> None:
    with connection.transaction():
        row = connection.execute(
            """UPDATE service_analysis SET status='failed', error_code=%s, finished_at=now()
               WHERE id=%s AND status='running' RETURNING request_id""", (code, analysis_id)).fetchone()
        if row:
            add_history(connection, row[0], f'분석 실패 · {code}')


def analysis_view(result: dict[str, Any]) -> dict[str, Any]:
    return {'summary': result['summary'], 'causes': result['causes'], 'steps': result['steps'],
            'questions': result['questions'], 'parts': result['parts'], 'evidence': result['evidence'],
            'caseSearch': result['case_search'], 'status': result['status'],
            'identifierChecks': result.get('identifier_checks', [])}
