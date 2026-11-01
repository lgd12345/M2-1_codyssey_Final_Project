// Pure helpers for the chat test screen (no React), so they can be unit-tested.

const HIDDEN_TOOLS = new Set(['final_result']) // the structured answer is shown only after the server validated it

/** Tool-call parts of an assistant message, in call order. */
export function toolSteps(parts = []) {
  return (parts || [])
    .filter((part) => typeof part?.type === 'string' && part.type.startsWith('tool-'))
    .map((part) => ({
      id: part.toolCallId, name: part.type.slice('tool-'.length), state: part.state,
      input: part.input || {}, output: part.output, errorText: part.errorText,
    }))
    .filter((step) => !HIDDEN_TOOLS.has(step.name))
}

const quote = (text) => `“${text}”`

function errorCode(output) {
  return output && output.ok === false ? output.error?.code || 'error' : null
}

/** Korean, human-readable view of one tool step. */
export function describeStep(step) {
  const { name, input, output, state } = step
  const done = state === 'output-available'
  let status = done ? 'done' : state === 'output-error' ? 'error' : 'running'
  let title = name
  let detail = ''
  let result = ''

  if (name === 'lookup_identifier') {
    title = '식별자 조회'
    detail = `${quote(input.value ?? '')}${input.kind ? ` (${input.kind})` : ''}`
    if (done) {
      if (errorCode(output)) { status = 'error'; result = `실패: ${errorCode(output)}` }
      else if (output?.status === 'unknown_identifier_kind') { status = 'error'; result = `알 수 없는 종류 (유효: ${(output.valid_kinds || []).join(', ')})` }
      else result = output?.found ? `일치 ${(output.matches || []).length}건` : '일치 없음'
    }
  } else if (name === 'search_manual') {
    title = '매뉴얼 검색'
    detail = [quote(input.query ?? ''), input.machines?.length ? `기종 ${input.machines.join('/')}` : ''].filter(Boolean).join(' · ')
    if (done) {
      if (errorCode(output)) { status = 'error'; result = `실패: ${errorCode(output)}` }
      else {
        const legs = Object.entries(output?.search_status || {})
          .map(([leg, value]) => `${leg}: ${typeof value === 'object' && value ? value.status : value}`).join(', ')
        result = `${(output?.results || []).length}건${legs ? ` · ${legs}` : ''}`
      }
    }
  } else if (name === 'open_source') {
    title = '원본 열람'
    detail = `PDF ${input.pdf_page ?? '?'}쪽`
    if (done) {
      if (errorCode(output)) { status = 'error'; result = `실패: ${errorCode(output)}` }
      else result = `열람 완료${output?.verification ? ` · 변환 검증 ${output.verification}` : ''}`
    }
  }
  if (state === 'output-error') result = '도구 실행 오류'
  return { title, detail, result, status }
}

const ASSET = /^asset:([A-Za-z0-9_-]+)$/

/** Image source from an answer's markdown. Only pages this run opened resolve; everything else is refused. */
export function resolveImage(src, assets) {
  const match = typeof src === 'string' ? ASSET.exec(src) : null
  const asset = match && (assets || []).find((item) => item.asset_id === match[1])
  return asset ? { url: asset.url, page: asset.pdf_page } : null
}

const ANSWER_LABELS = {
  answered: '근거 있는 답변',
  insufficient_evidence: '근거 부족',
  conversational: '일반 응답 (매뉴얼 근거 없음)',
}

/** Label for an answer status; only `answered` is presented as grounded in the manuals. */
export const answerLabel = (status) => ANSWER_LABELS[status] || ''

const ASSET_IMAGE = /!\[[^\]]*\]\(asset:[A-Za-z0-9_-]+\)/g

/**
 * Plain text kept in the chat history for the next turn (never tool parts, never unvalidated output).
 * Image references are replaced: their ids are only valid for the run that opened them, and a model that
 * copies a stale id into a later answer would have that answer rejected.
 */
export function historyText(run) {
  if (!run) return '(응답을 불러오지 못했습니다)'
  if (run.answer_markdown) return run.answer_markdown.replace(ASSET_IMAGE, '[원본 페이지 이미지]')
  return '(오류로 응답하지 못했습니다)'
}
