import test from 'node:test'
import assert from 'node:assert/strict'
import { toolSteps, describeStep, historyText, resolveImage, answerLabel } from './chat.js'

const parts = [
  { type: 'step-start' },
  { type: 'tool-lookup_identifier', toolCallId: 'a', state: 'output-available',
    input: { value: '2064-01-101-01', kind: 'part_number' }, output: { found: true, matches: [{}, {}] } },
  { type: 'tool-open_source', toolCallId: 'b', state: 'input-available', input: { doc_sha256: 'x', pdf_page: 9 } },
  { type: 'tool-final_result', toolCallId: 'c', state: 'output-available', input: { answer_markdown: 'unvalidated' } },
  { type: 'text', text: 'ignored' },
]

test('lists tool calls in order and hides the unvalidated final_result', () => {
  const steps = toolSteps(parts)
  assert.deepEqual(steps.map((s) => s.name), ['lookup_identifier', 'open_source'])
  assert.deepEqual(steps.map((s) => s.state), ['output-available', 'input-available'])
})

test('describes a finished lookup in Korean with its arguments and result', () => {
  const [lookup] = toolSteps(parts)
  assert.deepEqual(describeStep(lookup), {
    title: '식별자 조회', detail: '“2064-01-101-01” (part_number)', result: '일치 2건', status: 'done' })
})

test('a call that has not returned yet is shown as running', () => {
  const open = toolSteps(parts)[1]
  assert.deepEqual(describeStep(open), { title: '원본 열람', detail: 'PDF 9쪽', result: '', status: 'running' })
})

test('search results show the count and each retrieval leg', () => {
  const [step] = toolSteps([{ type: 'tool-search_manual', toolCallId: 's', state: 'output-available',
    input: { query: '서보 과열', machines: ['F400'] },
    output: { results: [{}, {}, {}], search_status: { keyword: 'ok', trigram: 'no_match', vector: { status: 'not_configured' } } } }])
  const view = describeStep(step)
  assert.equal(view.title, '매뉴얼 검색')
  assert.equal(view.detail, '“서보 과열” · 기종 F400')
  assert.equal(view.result, '3건 · keyword: ok, trigram: no_match, vector: not_configured')
})

test('tool failures and unknown kinds are surfaced as errors, not as empty results', () => {
  const failed = describeStep(toolSteps([{ type: 'tool-open_source', toolCallId: 'f', state: 'output-available',
    input: { pdf_page: 4 }, output: { ok: false, error: { code: 'source_missing' } } }])[0])
  assert.equal(failed.status, 'error')
  assert.match(failed.result, /source_missing/)
  const kind = describeStep(toolSteps([{ type: 'tool-lookup_identifier', toolCallId: 'k', state: 'output-available',
    input: { value: 'x', kind: 'serial' }, output: { found: false, status: 'unknown_identifier_kind' } }])[0])
  assert.equal(kind.status, 'error')
})

test('a model-side error state is an error step', () => {
  const view = describeStep(toolSteps([{ type: 'tool-search_manual', toolCallId: 'e', state: 'output-error',
    input: { query: 'q' }, errorText: 'boom' }])[0])
  assert.equal(view.status, 'error')
})

test('each answer status has its own label, so a reply without manual evidence is never shown as cited', () => {
  assert.equal(answerLabel('answered'), '근거 있는 답변')
  assert.equal(answerLabel('insufficient_evidence'), '근거 부족')
  assert.equal(answerLabel('conversational'), '일반 응답 (매뉴얼 근거 없음)')
  assert.equal(answerLabel(undefined), '')
})

const assets = [{ asset_id: 'a-1', url: '/api/v1/agent/runs/r/assets/a-1', pdf_page: 3 }]

test('only images the run opened resolve to a URL', () => {
  assert.deepEqual(resolveImage('asset:a-1', assets), { url: '/api/v1/agent/runs/r/assets/a-1', page: 3 })
  assert.equal(resolveImage('asset:unknown', assets), null)
  assert.equal(resolveImage('https://evil.example/x.png', assets), null)
  assert.equal(resolveImage('//evil.example/x.png', assets), null)
  assert.equal(resolveImage('javascript:alert(1)', assets), null)
  assert.equal(resolveImage(undefined, assets), null)
  assert.equal(resolveImage('asset:a-1', undefined), null)
})

test('history drops image references so a later turn cannot re-use an image it never opened', () => {
  const run = { answer_markdown: '앞 ![원본](asset:abc-1_x) 뒤 ![](asset:zzz)', status: 'succeeded' }
  const text = historyText(run)
  assert.doesNotMatch(text, /asset:/)
  assert.match(text, /앞 \[원본 페이지 이미지\] 뒤 \[원본 페이지 이미지\]/)
  assert.equal(historyText({ answer_markdown: '![x](https://example.test/a.png)' }), '![x](https://example.test/a.png)')
})

test('history sent back for the next turn is plain text only', () => {
  assert.equal(historyText({ answer_markdown: '답변 본문', status: 'succeeded' }), '답변 본문')
  assert.equal(historyText({ answer_markdown: null, status: 'failed', error_code: 'agent_error' }), '(오류로 응답하지 못했습니다)')
  assert.equal(historyText(null), '(응답을 불러오지 못했습니다)')
})
