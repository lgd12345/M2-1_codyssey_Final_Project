import { DEPARTMENTS } from './catalog.js'

// UI rules only. State transitions and authorization belong to the server.
export const STATUSES = ['접수됨', '분석 중', '검토 대기', '추가 정보 필요', '처리 중', '반려됨', '종결']
export const WORK_STATUSES = ['전달됨', '진행 중', '완료']
export const isEditable = item => ['검토 대기', '추가 정보 필요'].includes(item.status)
export const canReanalyze = item => ['검토 대기', '추가 정보 필요', '반려됨'].includes(item.status)
export const allWorkDone = item => item.linked.length > 0 && item.linked.every(work => work.status === '완료')
export const canResolve = item => item.status === '처리 중' && allWorkDone(item)
export const canStartAnalysis = item => Boolean(item) && item.status === '접수됨'
export const isAnalysisRunning = item => Boolean(item) && item.status === '분석 중'
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
export const isEdited = department => department.draft !== department.aiDraft
export function canApprove(item) {
  if (!isEditable(item) || !item.analysis) return false
  const selected = item.departments.filter(department => department.selected)
  return selected.length > 0 && selected.every(department => department.draft.trim().length > 0)
}
export const statusCounts = cases => Object.fromEntries(STATUSES.map(status => [status, cases.filter(item => item.status === status).length]))
const CUSTOMER_STATUS = { '접수됨': '접수됨', '분석 중': '접수됨', '검토 대기': '확인 중', '반려됨': '확인 중', '추가 정보 필요': '정보 요청', '처리 중': '처리 중', '종결': '완료' }
export const customerStatus = item => CUSTOMER_STATUS[item.status] ?? item.status
export function workItems(cases, deptKey) {
  const name = DEPARTMENTS.find(department => department.key === deptKey)?.name
  return cases.flatMap(item => (item.linked || []).filter(work => work.name === name).map(work => ({
    ...work, caseId: item.id, caseTitle: item.title, intake: item.intake, caseStatus: item.status, createdAt: item.approval?.at,
  })))
}
