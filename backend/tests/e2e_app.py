"""Browser E2E server: the real app with ONLY the model call replaced by a deterministic double.

Auth, sessions, CSRF, authorization, DB, validation, persistence and the UI stay real.
"""
import asyncio
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

import app.agent_rag.tools as agent_tools
from app.agent_rag.settings import AgentSettings
from app.service_requests import chat

from app.mail.deps import get_mail_sender
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
        'status': 'answered', 'summary': 'E2E 통제된 분석 응답: ' + request['machine']
        + (f" · 추가 정보 {len(request['additional_info'])}건 반영" if request.get('additional_info') else ''),
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
        'identifier_checks': [
            {'kind': 'alarm_number', 'value': '2023', 'status': 'found', 'source': 'server'},
            {'kind': 'part_no', 'value': '2064-75-114-00', 'status': 'not_found', 'source': 'server'}],
    }



class NoMail:
    """The browser tests never reach a real mail server, whatever the environment holds."""
    from_address = 'noreply@test.invalid'

    async def send(self, message):
        return None


app.dependency_overrides[get_mail_sender] = lambda: NoMail()


# --- operator chat: scripted model; retrieval of cases and manuals is stubbed (the E2E database has no corpus) ---
CHAT_CASE = {'found': True, 'fsr_no': 'FSR-00005', 'matched_fsr_no': 'FSR-00005', 'machine': 'VMCT-02',
             'registered_on': '2024-01-02', 'same_case_count': 1,
             'handlers': [{'fsr_no': 'FSR-00005', 'worker': 'EMP-0003', 'center': 'CENTER-003', 'branch': '천안직영센터'}]}
CHAT_CASES = {'query': 'q', 'results': [{
    'id': 1, 'fsr_no': 'FSR-00005', 'duplicate_fsr_nos': [], 'machine': 'VMCT-02', 'warranty': '', 'repair_type': '',
    'registered_on': None, 'symptom': ['ATC'], 'complaint': 'POT UP 신호 불량', 'resolution': 'UP 확인 센서 재조임',
    'requested_part': None, 'replacement_part': None, 'same_case_count': 1, 'resolution_detail': 'full',
    'content_hash': 'c' * 64}], 'search_status': {'keyword': 'ok'}}
CHAT_MANUAL = {'query': 'ATC', 'results': [{'content_hash': 'h' * 64, 'content': 'ATC 구동부 점검 절차', 'score': 1.0,
                                           'ranks': {}, 'table_evidence': None, 'sources': [{
                                               'document_sha256': 'e' * 64, 'pdf_page': 45, 'printed_page': '2-31',
                                               'title': 'E2E 매뉴얼', 'page_class': 'text', 'machine': 'F400',
                                               'verification': 'verified', 'page_id': 1, 'content': 'ATC 구동부 점검 절차'}]}],
                'search_status': {'keyword': 'ok'}}
chat.lookup_case = lambda value, **kwargs: CHAT_CASE
agent_tools.search_cases = lambda *args, **kwargs: CHAT_CASES
agent_tools.search_manual = lambda *args, **kwargs: CHAT_MANUAL


def _asked(messages):
    return ' '.join(str(getattr(part, 'content', '')) for message in messages for part in message.parts
                    if getattr(part, 'part_kind', '') == 'user-prompt')


def chat_plan(messages):
    if '메일 초안' in _asked(messages):
        if any(getattr(part, 'part_kind', '') == 'tool-return' for message in messages for part in message.parts):
            return [('text', '서비스 부서 메일 초안을 만들었습니다. 카드에서 확인하고 보내기를 눌러 주세요.')]
        return [('tool', 'draft_department_mail', {'department_key': 'service', 'subject': '[출동 요청] ATC 정지',
                                                   'body': 'F400 ATC 정지 증상입니다. 현장 점검을 부탁드립니다.'})]
    if any(getattr(part, 'part_kind', '') == 'tool-return' for message in messages for part in message.parts):
        return [('text', '비슷한 사례는 FSR-00005이며 담당 작업자는 EMP-0003입니다.')]
    return [('tool', 'search_cases', {'query': 'ATC'}), ('tool', 'lookup_case', {'fsr_no': 'FSR-00005'}),
            ('tool', 'search_manual', {'query': 'ATC'})]


def chat_model():
    def function(messages, info):
        parts = [ToolCallPart(s[1], s[2], tool_call_id=f'c{len(messages)}-{i}') if s[0] == 'tool' else TextPart(s[1])
                 for i, s in enumerate(chat_plan(messages))]
        return ModelResponse(parts=parts)

    async def stream(messages, info):
        for i, step in enumerate(chat_plan(messages)):
            if step[0] == 'tool':
                yield {i: DeltaToolCall(name=step[1], json_args=json.dumps(step[2]), tool_call_id=f'c{len(messages)}-{i}')}
            else:
                yield step[1]
    return FunctionModel(function, stream_function=stream)


@asynccontextmanager
async def chat_provider():
    yield chat_model()


app.dependency_overrides[chat.get_chat_runtime] = lambda: chat.ChatRuntime(
    chat_provider, AgentSettings('', '', '', 60, '', Path('cache'), 150))
app.dependency_overrides[get_analysis_runner] = lambda: controlled_model
app.dependency_overrides[get_page_renderer] = lambda: (lambda document_sha256, page: PAGE_PNG)
