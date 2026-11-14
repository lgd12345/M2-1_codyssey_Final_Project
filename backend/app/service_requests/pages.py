"""Original manual pages behind a request's citations.

The server decides which page to render from the citation it stored with the analysis; the client only names a
request and a citation id. Operators may open any manual citation. A customer may open the guides of an approved
request of their own company, which is exactly the list their request detail shows.
"""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from psycopg.rows import dict_row

from app.auth.deps import require_user
from app.auth.service import AuthError, SessionInfo
from app.service_requests.routes import RequestNotFound, access_company, request_database, request_number

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/service-requests', tags=['service-requests-pages'])
PageRenderer = Callable[[str, int], bytes]
CUSTOMER_VISIBLE = ('처리 중', '종결')  # reviewed and approved


class EvidenceNotFound(AuthError):
    status_code, code = 404, 'EVIDENCE_NOT_FOUND'
    message = '열람할 수 있는 원본 페이지가 없습니다.'


class SourceUnavailable(AuthError):
    status_code, code = 404, 'SOURCE_UNAVAILABLE'
    message = '원본 PDF 페이지를 열 수 없습니다. 관리자에게 문의해 주세요.'


def get_page_renderer() -> PageRenderer:
    """Dependency seam: tests replace this so no PDF is needed."""
    from app.agent_rag.pdf_source import render_indexed_page
    from app.agent_rag.settings import AgentSettings

    def render(document_sha256: str, page: int) -> bytes:
        settings = AgentSettings.from_env()
        return render_indexed_page(document_sha256, page, database_url=settings.database_url, dpi=settings.pdf_render_dpi)
    return render


@router.get('/{identity}/evidence/{evidence_id}/page')
def evidence_page(identity: str, evidence_id: str, session: SessionInfo = Depends(require_user),
                  render: PageRenderer = Depends(get_page_renderer)):
    number = request_number(identity)
    staff = session.user.role == 'admin'
    with request_database() as connection:
        company_id = access_company(connection, session)
        with connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """SELECT r.status, ok.result FROM service_request r
                   LEFT JOIN LATERAL (SELECT result FROM service_analysis WHERE request_id=r.id AND status='succeeded'
                                      ORDER BY created_at DESC, id DESC LIMIT 1) ok ON TRUE
                   WHERE r.id=%s AND (%s OR r.company_id=%s)""", (number, staff, company_id)).fetchone()
    if row is None:
        raise RequestNotFound()
    if not staff and row['status'] not in CUSTOMER_VISIBLE:
        raise EvidenceNotFound()  # not reviewed yet: indistinguishable from a citation that does not exist
    evidence = next((e for e in (row['result'] or {}).get('evidence', []) if e['id'] == evidence_id), None)
    ref = evidence.get('ref') if evidence and evidence['kind'] == 'manual' else None
    if not ref:
        raise EvidenceNotFound()
    try:
        image = render(ref['document_sha256'], ref['page'])
    except (FileNotFoundError, LookupError, ValueError, OSError, RuntimeError) as error:
        logger.warning('original page unavailable: %s', type(error).__name__)  # never the message: it may hold paths
        raise SourceUnavailable() from None
    return Response(content=image, media_type='image/png',
                    headers={'Cache-Control': 'private, max-age=300', 'X-Content-Type-Options': 'nosniff'})
