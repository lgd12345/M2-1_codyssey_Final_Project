import test from 'node:test'
import assert from 'node:assert/strict'
import { analysisRunNotice, canApprove, canReanalyze, canStartAnalysis, isAnalysisRunning, canResolve, customerStatus, isEditable, isEdited, statusCounts, workItems, identifierCheckLine } from './domain/workflow.js'

const request = (extra = {}) => ({ id: 'CLM-1000', status: '검토 대기', analysis: { summary: '실제 분석 결과' },
  departments: [{ key: 'service', selected: true, aiDraft: '원본', draft: '원본' }], linked: [], ...extra })

test('an unanalysed received request is not reviewable, approvable or resolved', () => {
  const item = request({ status: '접수됨', analysis: null })
  assert.equal(canApprove(item), false)
  assert.equal(isEditable(item), false)
  assert.equal(canResolve(item), false)
  assert.equal(canReanalyze(item), false)
})
for (const status of ['검토 대기', '추가 정보 필요']) {
  test(`${status}: approval needs analysis, a selected department and nonblank drafts`, () => {
    const item = request({ status })
    assert.equal(canApprove(item), true)
    assert.equal(canApprove({ ...item, analysis: null }), false)
    assert.equal(canApprove({ ...item, departments: [] }), false)
    assert.equal(canApprove({ ...item, departments: [{ selected: false, draft: 'x' }] }), false)
    assert.equal(canApprove({ ...item, departments: [{ selected: true, draft: '  ' }] }), false)
  })
}
for (const status of ['분석 중', '반려됨', '처리 중', '종결']) {
  test(`${status} cannot approve or edit department drafts`, () => {
    assert.equal(canApprove(request({ status })), false)
    assert.equal(isEditable(request({ status })), false)
  })
}
test('only review, additional information and declined requests can be reanalysed', () => {
  for (const status of ['검토 대기', '추가 정보 필요', '반려됨']) assert.equal(canReanalyze({ status }), true)
  for (const status of ['접수됨', '분석 중', '처리 중', '종결']) assert.equal(canReanalyze({ status }), false)
})
test('closing requires processing state and at least one linked work, all completed', () => {
  assert.equal(canResolve(request({ status: '처리 중' })), false)
  assert.equal(canResolve(request({ status: '처리 중', linked: [{ status: '진행 중' }] })), false)
  assert.equal(canResolve(request({ status: '처리 중', linked: [{ status: '완료' }, { status: '완료' }] })), true)
  assert.equal(canResolve(request({ status: '종결', linked: [{ status: '완료' }] })), false)
})
test('public status projection does not expose internal review and decline states', () => {
  const states = ['접수됨', '분석 중', '검토 대기', '추가 정보 필요', '반려됨', '처리 중', '종결']
  assert.deepEqual(states.map(status => customerStatus({ status })), ['접수됨', '접수됨', '확인 중', '정보 요청', '확인 중', '처리 중', '완료'])
})
test('department work lists contain only work actually returned by the server', () => {
  assert.deepEqual(workItems([], 'sales'), [])
  const item = request({ title: '요청', intake: {}, approval: { at: '2026-01-01' },
    linked: [{ name: '영업', workKey: 'SAL-1000' }, { name: '서비스', workKey: 'SVC-1000' }] })
  assert.deepEqual(workItems([item], 'sales').map(x => x.workKey), ['SAL-1000'])
})
test('empty queues have zero counts and no generated sample data', () => {
  assert.ok(Object.values(statusCounts([])).every(n => n === 0))
  assert.equal(statusCounts([request({ status: '접수됨' })])['접수됨'], 1)
})
test('AI original and reviewer edit remain distinct', () => {
  assert.equal(isEdited({ aiDraft: '원본', draft: '원본' }), false)
  assert.equal(isEdited({ aiDraft: '원본', draft: '검토 수정' }), true)
})

test('only a received request without a running analysis can start analysis', () => {
  assert.equal(canStartAnalysis(request({ status: '접수됨', analysis: null })), true)
  assert.equal(canStartAnalysis(request({ status: '접수됨', analysis: null, analysisRun: { status: 'failed', errorCode: 'agent_error' } })), true)
  for (const status of ['분석 중', '검토 대기', '추가 정보 필요', '처리 중', '반려됨', '종결']) {
    assert.equal(canStartAnalysis(request({ status })), false, status)
  }
  assert.equal(canStartAnalysis(null), false)
})

test('a running analysis is detected from the server state and drives polling', () => {
  assert.equal(isAnalysisRunning(request({ status: '분석 중' })), true)
  assert.equal(isAnalysisRunning(request({ status: '검토 대기' })), false)
  assert.equal(isAnalysisRunning(null), false)
})

test('failed analysis notices are honest, actionable and never expose internals', () => {
  assert.equal(analysisRunNotice(null), '')
  assert.equal(analysisRunNotice({ status: 'succeeded', errorCode: null }), '')
  assert.match(analysisRunNotice({ status: 'failed', errorCode: 'llm_unavailable' }), /AI 모델에 연결하지 못했습니다/)
  assert.match(analysisRunNotice({ status: 'failed', errorCode: 'invalid_analysis' }), /근거가 확인되지 않아/)
  assert.match(analysisRunNotice({ status: 'failed', errorCode: 'interrupted' }), /서버가 재시작되어/)
  const unknown = analysisRunNotice({ status: 'failed', errorCode: 'surprising_new_code' })
  assert.match(unknown, /분석에 실패했습니다/)
  assert.doesNotMatch(unknown, /surprising_new_code/)
})

test('identifier checks read as one line each and never call a miss a verified absence', () => {
  const line = (kind, status, source = 'server') => identifierCheckLine({ kind, value: '2023', status, source })
  assert.equal(line('alarm_number', 'found'), '알람 2023: 색인된 매뉴얼에서 찾음')
  assert.equal(line('part_no', 'not_found'), '부품번호 2023: 색인된 매뉴얼에서 찾지 못함')
  assert.equal(line('pmc_address', 'check_failed'), 'PMC 주소 2023: 조회하지 못함')
  assert.equal(line('drawing_no', 'found', 'agent'), '도면번호 2023: 색인된 매뉴얼에서 찾음 (AI 추가 조회)')
  assert.equal(line('mystery', 'found'), '식별자 2023: 색인된 매뉴얼에서 찾음')
})
