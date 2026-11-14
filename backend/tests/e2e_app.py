"""Browser E2E server: the real app with ONLY the model call replaced by a deterministic double.

Auth, sessions, CSRF, authorization, DB, validation, persistence and the UI stay real.
"""
import asyncio
import base64

from app.main import app
from app.service_requests.analysis import get_analysis_runner
from app.service_requests.pages import get_page_renderer

# 1x1 PNG: stands in for the rendered PDF page, so the browser really decodes an image. No PDF is used here.
PAGE_PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


analysed: set[tuple[str, str]] = set()


async def controlled_model(request):
    await asyncio.sleep(1.2)  # long enough for the browser to observe the running state
    # A request whose text says so lacks evidence the first time it is analysed; a re-analysis then finds some.
    first_time = (request['message'], request['machine']) not in analysed
    analysed.add((request['message'], request['machine']))
    if '근거부족' in request['message'] and first_time:
        return {'status': 'insufficient_evidence', 'summary': 'E2E 근거 부족 응답', 'causes': [], 'steps': [],
                'questions': ['알람 번호를 알려주세요.'], 'parts': [], 'evidence': [], 'departments': [], 'case_search': 'ok'}
    return {
        'status': 'answered', 'summary': 'E2E 통제된 분석 응답: ' + request['machine'],
        'causes': [{'title': 'ATC 암 구동 불량', 'level': '높음', 'detail': '교환 중 정지 증상', 'evidence': ['E1', 'E2']}],
        'steps': ['알람 이력 확인', 'ATC 암 점검'], 'questions': ['정지 위치를 알려주세요.'],
        'parts': [{'name': 'ATC 암 모터', 'note': '마모 시 교체', 'source': 'E2E 매뉴얼 p.45'}],
        'evidence': [
            {'id': 'E1', 'kind': 'manual', 'title': 'E2E 매뉴얼', 'source': 'E2E 매뉴얼 p.45',
             'excerpt': 'ATC 구동부 점검 절차', 'note': '변환 텍스트입니다.', 'ref': {'document_sha256': 'e' * 64, 'page': 45}},
            {'id': 'E2', 'kind': 'fsr', 'title': 'FSR-00001', 'source': 'FSR-00001 · VMCT-05',
             'excerpt': '공구 교환 중 정지', 'note': '과거 사례는 참고용입니다.'}],
        'departments': [{'key': 'service', 'reason': '현장 점검 필요', 'draft': 'ATC 점검 방문 초안'}],
        'case_search': 'ok',
    }


app.dependency_overrides[get_analysis_runner] = lambda: controlled_model
app.dependency_overrides[get_page_renderer] = lambda: (lambda document_sha256, page: PAGE_PNG)
