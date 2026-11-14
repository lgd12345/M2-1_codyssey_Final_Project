"""Analysis lifecycle for stored requests: begin -> (model runner) -> validated, durable result.

Nothing here approves a request or creates department work; it only produces a reviewable analysis.
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
    message = '접수됨 상태의 요청만 분석을 시작할 수 있습니다.'


class AnalysisRequestNotFound(AuthError):
    status_code, code = 404, 'REQUEST_NOT_FOUND'
    message = '요청 또는 장비를 찾을 수 없습니다.'


def get_analysis_runner() -> AnalysisRunner:
    """Dependency seam: tests replace this so no real model is called."""
    from app.service_requests.analyzer import analyze_request
    return analyze_request


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Evidence(_Model):
    id: str = Field(min_length=1, max_length=20)
    kind: Literal['fsr', 'manual']
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    excerpt: str
    note: str


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
    return AnalysisResult.model_validate(raw).model_dump(mode='json')


class InvalidAnalysis(ValueError):
    pass


def error_code_for(error: BaseException) -> str:
    if isinstance(error, (ValidationError, InvalidAnalysis)):
        return 'invalid_analysis'
    from pydantic_ai.exceptions import ModelAPIError
    if isinstance(error, ModelAPIError):  # connection, timeout, rate limit, overload, quota: the model is not usable now
        return 'llm_unavailable'
    from app.runs.service import error_code_for as run_error_code
    return run_error_code(error)


def recover_orphans(connection) -> None:
    with connection.transaction():
        connection.execute(
            """WITH failed AS (UPDATE service_analysis SET status='failed', error_code='interrupted', finished_at=now()
                                WHERE status='running' AND worker_id <> %s RETURNING request_id, previous_status)
               UPDATE service_request r SET status=f.previous_status
               FROM failed f WHERE r.status='분석 중' AND r.id=f.request_id""", (PROCESS_ID,))


def add_history(connection, number: int, text: str, public_text: str | None = None) -> None:
    connection.execute('INSERT INTO service_history(request_id,text,public_text) VALUES (%s,%s,%s)',
                       (number, text, public_text))


def begin(connection, number: int, user_id: UUID, *, allowed: tuple[str, ...] = ('접수됨',),
          history: str | None = None) -> tuple[UUID, dict[str, Any]]:
    """Atomically claim a request for (re-)analysis and return the stored facts the model may use."""
    recover_orphans(connection)
    with connection.transaction():
        row = connection.execute(
            'SELECT status,message,reason,alarm_numbers,equipment_snapshot FROM service_request WHERE id=%s FOR UPDATE',
            (number,)).fetchone()
        if row is None:
            raise AnalysisRequestNotFound()
        if row[0] == '분석 중':
            raise AnalysisInProgress()
        if row[0] not in allowed:
            raise AnalysisNotAllowed()
        analysis_id = connection.execute(
            'INSERT INTO service_analysis(request_id,requested_by,worker_id,previous_status) VALUES (%s,%s,%s,%s) RETURNING id',
            (number, user_id, PROCESS_ID, row[0])).fetchone()[0]
        connection.execute("UPDATE service_request SET status='분석 중' WHERE id=%s", (number,))
        if history:
            add_history(connection, number, history)
        # Customer additions are facts the analysis should consider; callbacks and closure requests are not.
        additional = [r[0] for r in connection.execute(
            "SELECT text FROM service_comment WHERE request_id=%s AND kind='customer' AND intent='reply' ORDER BY created_at,id",
            (number,)).fetchall()]
    snapshot = row[4]
    # Only diagnostic facts: the customer's contact details are deliberately not sent to a model.
    return analysis_id, {'message': row[1], 'reason': row[2], 'alarm_numbers': list(row[3]),
                         'machine': snapshot['machine'], 'serial': snapshot['serial'], 'additional_info': additional}


def finish_success(connection, analysis_id: UUID, result: dict[str, Any]) -> None:
    with connection.transaction():
        row = connection.execute(
            """UPDATE service_analysis SET status='succeeded', result=%s, finished_at=now()
               WHERE id=%s AND status='running' RETURNING request_id""",
            (Jsonb(result, dumps=lambda item: json.dumps(item, ensure_ascii=False)), analysis_id)).fetchone()
        if not row:
            return
        number = row[0]
        # A new analysis replaces earlier recommendations and any review edits made to them.
        connection.execute('DELETE FROM service_request_department WHERE request_id=%s', (number,))
        recommended = {item['key']: item for item in result['departments']}
        for key in DEPARTMENT_KEYS:
            item = recommended.get(key)
            draft = item['draft'] if item else ''
            connection.execute(
                """INSERT INTO service_request_department(request_id,key,ai_selected,selected,reason,ai_draft,draft)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (number, key, item is not None, item is not None, item['reason'] if item else NO_RECOMMENDATION, draft, draft))
        # Without enough evidence the customer is asked for more information instead of a review.
        insufficient = result['status'] == 'insufficient_evidence'
        connection.execute(
            """UPDATE service_request SET status=%s,
                      revision=(SELECT count(*) FROM service_analysis WHERE request_id=%s AND status='succeeded')
               WHERE id=%s AND status='분석 중'""", ('추가 정보 필요' if insufficient else '검토 대기', number, number))
        add_history(connection, number, '분석 완료 · 근거 부족, 추가 정보 필요' if insufficient else '분석 완료 · 검토 대기')


def finish_failure(connection, analysis_id: UUID, code: str) -> None:
    with connection.transaction():
        row = connection.execute(
            """UPDATE service_analysis SET status='failed', error_code=%s, finished_at=now()
               WHERE id=%s AND status='running' RETURNING request_id, previous_status""", (code, analysis_id)).fetchone()
        if row:
            connection.execute("UPDATE service_request SET status=%s WHERE id=%s AND status='분석 중'", (row[1], row[0]))
            add_history(connection, row[0], f'분석 실패 · {code}')


def analysis_view(result: dict[str, Any]) -> dict[str, Any]:
    return {'summary': result['summary'], 'causes': result['causes'], 'steps': result['steps'],
            'questions': result['questions'], 'parts': result['parts'], 'evidence': result['evidence'],
            'caseSearch': result['case_search'], 'status': result['status']}
