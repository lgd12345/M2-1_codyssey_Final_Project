// UI rules only. State transitions and authorization belong to the server.
// 접수됨 -> 처리 중 (the first analysis starts) -> 종결 (an operator writes the result).
export const STATUSES = ['접수됨', '처리 중', '종결']
export const isAnalysisRunning = item => item?.analysisRun?.status === 'running'  // the request is 처리 중 from the start: ask the run
export const canStartAnalysis = item => Boolean(item) && item.status !== '종결' && !item.analysis && !isAnalysisRunning(item)
export const canReanalyze = item => Boolean(item) && item.status === '처리 중' && Boolean(item.analysis) && !isAnalysisRunning(item)
// Information gathered outside the app feeds the next analysis.
export const canAddInfo = item => Boolean(item) && item.status === '처리 중' && Boolean(item.analysis)
export const canResolve = item => Boolean(item) && item.status === '처리 중'
// The screen reveals itself in order: the analysis button first; the conversation, mail activities and the rest once an analysis exists.
export const chatReady = item => Boolean(item?.analysis)
export const showsDepartments = chatReady
// Notes and replies are possible after an analysis, and also when it failed so that the operator is never locked out.
export const showsActivityInput = item => Boolean(item) && (Boolean(item.analysis) || item.analysisRun?.status === 'failed')
const RUN_FAILURES = {
  llm_unavailable: 'AI 모델에 연결하지 못했습니다.',
  agent_not_configured: 'AI 분석 설정이 완료되지 않았습니다.',
  invalid_analysis: '출처로 쓴 근거가 확인되지 않아 분석 결과를 저장하지 않았습니다.',
  invalid_agent_output: '출처로 쓴 근거가 확인되지 않아 분석 결과를 저장하지 않았습니다.',
  database_unavailable: '데이터베이스에 연결하지 못했습니다.',
  interrupted: '서버가 재시작되어 분석이 중단되었습니다.',
}
export function analysisRunNotice(run) {
  if (run?.status !== 'failed') return ''
  return `분석에 실패했습니다. ${RUN_FAILURES[run.errorCode] ?? ''} 다시 시도할 수 있습니다.`.replace('  ', ' ')
}
export const statusCounts = cases => Object.fromEntries(STATUSES.map(status => [status, cases.filter(item => item.status === status).length]))
const CUSTOMER_STATUS = { '접수됨': '접수됨', '처리 중': '처리 중', '종결': '완료' }
export const customerStatus = item => CUSTOMER_STATUS[item.status] ?? item.status

const IDENTIFIER_KINDS = { alarm_number: '알람', part_no: '부품번호', drawing_no: '도면번호', pmc_address: 'PMC 주소' }
const IDENTIFIER_OUTCOMES = { found: '색인된 매뉴얼에서 찾음', not_found: '색인된 매뉴얼에서 찾지 못함', check_failed: '조회하지 못함' }
// "Not found" only says the indexed manuals have no exact match, so the wording never claims the number does not exist.
export const identifierCheckLine = check =>
  `${IDENTIFIER_KINDS[check.kind] || '식별자'} ${check.value}: ${IDENTIFIER_OUTCOMES[check.status]}${check.source === 'agent' ? ' (AI 추가 조회)' : ''}`

const MAIL_KINDS = { received: '접수 확인', approved: '처리 시작', resolved: '완료 안내' }
const MAIL_STATES = { pending: '발송 대기', sending: '발송 중', sent: '발송됨', failed: '발송 실패', skipped: '이메일 주소가 없어 보내지 않음' }
// Delivery state of the customer notifications, for operators only (the address itself is never sent to the browser).
export const mailLines = mail => (mail ?? []).map(entry => `${MAIL_KINDS[entry.kind]}: ${MAIL_STATES[entry.status]}`)
