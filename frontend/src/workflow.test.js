import test from 'node:test'
import assert from 'node:assert/strict'
import { analysisRunNotice, canReanalyze, canStartAnalysis, isAnalysisRunning, canResolve, chatReady, customerStatus, showsActivityInput, showsDepartments, statusCounts, identifierCheckLine, canAddInfo, mailLines, STATUSES } from './domain/workflow.js'

const request = (extra = {}) => ({ id: 'CLM-1000', status: '처리 중', analysis: { summary: '실제 분석 결과' },
  analysisRun: { status: 'succeeded', errorCode: null }, ...extra })

test('a request is 접수됨, 처리 중 or 종결: nothing else', () => {
  assert.deepEqual(STATUSES, ['접수됨', '처리 중', '종결'])
})

test('closing needs a request that is being processed and no analysis running', () => {
  assert.equal(canResolve(request()), true)
  assert.equal(canResolve(request({ analysisRun: { status: 'running', errorCode: null } })), false)
  assert.equal(canResolve(request({ analysis: null })), true)  // the operator may close even if the analysis failed
  for (const status of ['접수됨', '종결']) assert.equal(canResolve(request({ status })), false, status)
})

test('re-analysis and additional information need a request being processed that already has an analysis', () => {
  assert.equal(canReanalyze(request()), true)
  assert.equal(canReanalyze(request({ analysis: null })), false)
  assert.equal(canReanalyze(request({ analysisRun: { status: 'running' } })), false)  // one analysis at a time
  for (const status of ['접수됨', '종결']) assert.equal(canReanalyze(request({ status })), false, status)
  assert.equal(canAddInfo(request()), true)
  assert.equal(canAddInfo(request({ status: '종결' })), false)
  assert.equal(canAddInfo(request({ status: '접수됨', analysis: null })), false)
})

test('customers see 접수됨, 처리 중 and 완료 only', () => {
  assert.deepEqual(['접수됨', '처리 중', '종결'].map(status => customerStatus({ status })), ['접수됨', '처리 중', '완료'])
})

test('the first analysis can be started until one succeeds, and never while one runs', () => {
  assert.equal(canStartAnalysis(request({ status: '접수됨', analysis: null, analysisRun: null })), true)
  assert.equal(canStartAnalysis(request({ analysis: null, analysisRun: { status: 'failed', errorCode: 'agent_error' } })), true)  // retry after a failure
  assert.equal(canStartAnalysis(request({ analysis: null, analysisRun: { status: 'running', errorCode: null } })), false)
  assert.equal(canStartAnalysis(request()), false)
  assert.equal(canStartAnalysis(request({ status: '종결', analysis: null })), false)
  assert.equal(canStartAnalysis(null), false)
})

test('a running analysis is read from the run itself, since the request is already 처리 중', () => {
  assert.equal(isAnalysisRunning(request({ analysisRun: { status: 'running', errorCode: null } })), true)
  assert.equal(isAnalysisRunning(request()), false)
  assert.equal(isAnalysisRunning(request({ status: '접수됨', analysisRun: null })), false)
  assert.equal(isAnalysisRunning(null), false)
})

test('the screen discloses its parts in order: first the analysis button, then everything else', () => {
  const fresh = request({ status: '접수됨', analysis: null, analysisRun: null })
  const running = request({ analysis: null, analysisRun: { status: 'running', errorCode: null } })
  const failed = request({ analysis: null, analysisRun: { status: 'failed', errorCode: 'agent_error' } })
  const done = request()
  assert.deepEqual([fresh, running, failed, done].map(chatReady), [false, false, false, true])
  assert.deepEqual([fresh, running, failed, done].map(showsDepartments), [false, false, false, true])
  assert.deepEqual([fresh, running, failed, done].map(showsActivityInput), [false, false, true, true])  // a failed analysis must not lock the operator out
  assert.equal(showsActivityInput(request({ status: '종결' })), false)  // nothing more is written to a closed request
})

test('empty queues have zero counts and no generated sample data', () => {
  assert.ok(Object.values(statusCounts([])).every(n => n === 0))
  assert.equal(statusCounts([request({ status: '접수됨' })])['접수됨'], 1)
})
test('only a received request without a running analysis can start analysis', () => {
  assert.equal(canStartAnalysis(request({ status: '접수됨', analysis: null })), true)
  assert.equal(canStartAnalysis(request({ status: '접수됨', analysis: null, analysisRun: { status: 'failed', errorCode: 'agent_error' } })), true)
  for (const status of ['분석 중', '검토 대기', '추가 정보 필요', '처리 중', '반려됨', '종결']) {
    assert.equal(canStartAnalysis(request({ status })), false, status)
  }
  assert.equal(canStartAnalysis(null), false)
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

test('operators read mail delivery as one line per notification, failures and skips included', () => {
  assert.deepEqual(mailLines([
    { kind: 'received', status: 'sent' }, { kind: 'approved', status: 'failed' }, { kind: 'resolved', status: 'skipped' },
  ]), ['접수 확인: 발송됨', '처리 시작: 발송 실패', '완료 안내: 이메일 주소가 없어 보내지 않음'])
  assert.deepEqual(mailLines(undefined), [])
  assert.deepEqual(mailLines([{ kind: 'received', status: 'pending' }, { kind: 'received', status: 'sending' }]), ['접수 확인: 발송 대기', '접수 확인: 발송 중'])
})
