// Pure helpers of the operator chat: what to show for tool calls and how little the browser sends.
const SHA = /^[0-9a-f]{64}$/
const REQUEST = /^CLM-\d{3,19}$/

export const CHIPS = [
  { label: '분석 결과 요약', text: '현재 AI 분석 결과를 요약하고 근거를 알려 주세요.' },
  { label: '사례 담당자는?', text: '이 요청과 비슷한 과거 사례를 찾아 각 사례의 담당 작업자와 거점을 알려 주세요.' },
  { label: '현장에서 확인할 것', text: '전화나 현장에서 확인하면 좋을 사항을 근거와 함께 정리해 주세요.' },
  { label: '관련 매뉴얼 근거', text: '이 증상과 관련된 매뉴얼 근거와 해당 페이지를 알려 주세요.' },
]

const LABELS = {
  search_cases: '과거 사례 검색', search_manual: '매뉴얼 검색', lookup_identifier: '번호 조회',
  open_source: '원본 페이지 열람', lookup_case: '사례 담당 기록 조회',
  get_history: '이력 조회', list_mail_drafts: '메일 목록 조회', read_mail_draft: '메일 내용 조회',
  list_departments: '부서 목록 조회', draft_department_mail: '메일 초안 작성', propose_reanalysis: '재분석 제안',
}
export const toolLabel = name => LABELS[name] ?? name

export function toolStatus(part) {
  if (part.state === 'output-error') return 'failed'
  if (part.state !== 'output-available') return 'running'
  return part.output?.ok === false ? 'failed' : 'done'
}

const toolName = part => (typeof part?.type === 'string' && part.type.startsWith('tool-') ? part.type.slice(5) : null)
const finished = part => part?.state === 'output-available' && part.output && part.output.ok !== false

const documentOf = source => (source && SHA.test(source.document_sha256 ?? '') && Number.isInteger(source.pdf_page)
  ? { sha: source.document_sha256, page: source.pdf_page, title: source.title ?? '', label: `${source.title ?? '매뉴얼'} p.${source.printed_page || source.pdf_page}` }
  : null)

// Cases, manual pages and handlers a message's tool calls actually returned (never what the model merely wrote).
export function evidenceFrom(parts) {
  const cases = new Map(), documents = new Map(), handlers = new Map()
  for (const part of parts ?? []) {
    const name = toolName(part)
    if (!name || !finished(part)) continue
    const output = part.output
    if (name === 'search_cases') {
      for (const c of output.results ?? []) if (c?.fsr_no && !cases.has(c.fsr_no)) cases.set(c.fsr_no, c)
    } else if (name === 'search_manual') {
      for (const r of output.results ?? []) for (const s of r.sources ?? []) { const d = documentOf(s); if (d) documents.set(`${d.sha}:${d.page}`, d) }
    } else if (name === 'lookup_identifier') {
      for (const m of output.matches ?? []) { const d = documentOf(m); if (d) documents.set(`${d.sha}:${d.page}`, d) }
    } else if (name === 'lookup_case' && output.found) {
      for (const h of output.handlers ?? []) handlers.set(h.fsr_no, h)
    }
  }
  return { cases: [...cases.values()], documents: [...documents.values()], handlers: [...handlers.values()] }
}

export function chatPageUrl(id, sha, page) {
  if (!REQUEST.test(id ?? '') || !SHA.test(sha ?? '') || !Number.isInteger(page) || page < 1) throw new Error('올바르지 않은 원본 페이지 주소입니다.')
  return `/api/v1/service-requests/${id}/chat/page?document_sha256=${sha}&page=${page}`
}

// The server holds the conversation: only the newest message travels.
export const transportBody = ({ id, messages, trigger }) => ({ id, trigger, messages: messages.slice(-1) })

// One answer is stored as several assistant messages (tool calls, then text): show them as a single turn.
export function groupTurns(messages) {
  const turns = []
  for (const message of messages ?? []) {
    const last = turns[turns.length - 1]
    if (message.role === 'assistant' && last?.role === 'assistant') last.parts = [...last.parts, ...(message.parts ?? [])]
    else turns.push({ id: message.id, role: message.role, metadata: message.metadata, parts: [...(message.parts ?? [])] })
  }
  return turns
}

export function handlerLine(handler) {
  const bits = [handler.fsr_no]
  if (!handler.worker && !handler.center && !handler.branch) return `${handler.fsr_no} · 담당 기록 없음`
  bits.push(handler.worker ? `작업자 ${handler.worker}` : '작업자 기록 없음')
  if (handler.branch) bits.push(handler.branch)
  if (handler.center) bits.push(handler.center)
  return bits.join(' · ')
}

const DRAFT_STATES = { draft: '초안 · 아직 보내지 않았습니다', sending: '보내는 중', sent: '발송됨', failed: '발송 실패 · 다시 보낼 수 있습니다', cancelled: '취소됨' }
export const draftStateLabel = status => DRAFT_STATES[status] ?? status

export function mailDraftUrl(id, draftId, action) {
  if (!REQUEST.test(id ?? '') || !Number.isInteger(draftId) || draftId < 1 || !['send', 'cancel'].includes(action)) throw new Error('올바르지 않은 메일 주소입니다.')
  return `/service-requests/${id}/mail-drafts/${draftId}/${action}`
}

const timeOf = value => { const n = Date.parse(value ?? ''); return Number.isNaN(n) ? null : n }

// Analyses (oldest first) and the stored/streamed chat turns as one list in the order they happened.
// A turn without a time (one just sent) follows the turn before it, so it never jumps ahead of earlier answers.
export function timeline(messages, analyses) {
  const entries = []
  let carry = null
  groupTurns(messages).forEach((turn, index) => {
    const own = timeOf(turn.metadata?.pydantic_ai?.timestamp)
    const at = own ?? carry ?? Number.POSITIVE_INFINITY
    carry = own ?? carry
    entries.push({ kind: 'turn', ...turn, at, order: index + 1 })
  })
  const list = analyses ?? []
  list.forEach((entry, index) => entries.push({
    kind: 'analysis', revision: entry.revision, analysis: entry.analysis, at: timeOf(entry.at) ?? 0,
    current: index === list.length - 1, order: 0,
  }))
  return entries.sort((a, b) => (a.at === b.at ? a.order - b.order : a.at < b.at ? -1 : 1))
}

// Cards for what the agent proposed. A proposal is only a proposal until the operator confirms it.
const PROPOSALS = {
  reanalysis: { title: '재분석 제안', pending: '아직 실행하지 않았습니다', done: '재분석을 시작했습니다', confirm: '재분석 시작' },
}
export function proposalCard(proposal) {
  const base = PROPOSALS[proposal.kind]
  if (!base) return null
  const state = proposal.status === 'confirmed' ? base.done : proposal.status === 'cancelled' ? '취소했습니다' : base.pending
  return {
    title: base.title, state, confirm: base.confirm, open: proposal.status === 'pending',
    detail: '접수 내용을 기준으로 분석을 다시 실행합니다.',
  }
}

export function proposalUrl(id, proposalId, action) {
  if (!REQUEST.test(id ?? '') || !Number.isInteger(proposalId) || proposalId < 1 || !['confirm', 'cancel'].includes(action)) throw new Error('올바르지 않은 제안 주소입니다.')
  return `/service-requests/${id}/proposals/${proposalId}/${action}`
}

// The conversation is about an analysis: before the first one only the `분석 시작` button works.
export const chatOpen = item => Boolean(item?.analysis)
