import test from 'node:test'
import assert from 'node:assert/strict'
import { CHIPS, chatPageUrl, evidenceFrom, draftStateLabel, groupTurns, handlerLine, mailDraftUrl, toolLabel, toolStatus, transportBody } from './domain/chat.js'

const SHA = 'a'.repeat(64)
const part = (name, output, state = 'output-available') => ({ type: `tool-${name}`, toolCallId: `c-${name}`, state, input: {}, output })

test('every suggestion chip is a short ready-to-send question', () => {
  assert.ok(CHIPS.length >= 4)
  for (const chip of CHIPS) {
    assert.ok(chip.label.length <= 16 && chip.text.length > 5 && chip.text.length <= 2000)
  }
  assert.equal(new Set(CHIPS.map(chip => chip.label)).size, CHIPS.length)
})

test('tools are named in plain Korean and unknown ones stay readable', () => {
  assert.equal(toolLabel('lookup_case'), '사례 담당 기록 조회')
  assert.equal(toolLabel('search_manual'), '매뉴얼 검색')
  assert.equal(toolLabel('something_new'), 'something_new')
})

test('a tool part is running, done or failed from its state and output', () => {
  assert.equal(toolStatus({ state: 'input-streaming' }), 'running')
  assert.equal(toolStatus({ state: 'input-available' }), 'running')
  assert.equal(toolStatus({ state: 'output-available', output: { ok: true } }), 'done')
  assert.equal(toolStatus({ state: 'output-available', output: { ok: false, error: { code: 'tool_budget_exhausted' } } }), 'failed')
  assert.equal(toolStatus({ state: 'output-error' }), 'failed')
})

test('evidence cards are built from tool outputs: cases, manual pages and handlers, without duplicates', () => {
  const parts = [
    { type: 'text', text: '답' },
    part('search_cases', { results: [{ fsr_no: 'FSR-00005', machine: 'VMCT-02', complaint: 'UP 신호 불량', resolution: '센서 재조임' },
                                      { fsr_no: 'FSR-00024', machine: 'VMCT-06', complaint: '진동', resolution: '볼트 교체' }] }),
    part('search_manual', { results: [{ excerpt: 'ATC 점검', sources: [{ document_sha256: SHA, title: 'F400 매뉴얼', pdf_page: 45, printed_page: '2-31' }] },
                                       { excerpt: '또', sources: [{ document_sha256: SHA, title: 'F400 매뉴얼', pdf_page: 45, printed_page: '2-31' }] }] }),
    part('lookup_case', { found: true, fsr_no: 'FSR-00005', handlers: [{ fsr_no: 'FSR-00005', worker: 'EMP-0003', center: 'CENTER-003', branch: '천안직영센터' }] }),
    part('lookup_case', { found: false, fsr_no: 'FSR-1', status: 'not_found' }),
    part('lookup_identifier', { found: true, matches: [{ document_sha256: SHA, title: 'F400 매뉴얼', pdf_page: 46, printed_page: '2-32', excerpt: '2023' }] }),
  ]
  const evidence = evidenceFrom(parts)
  assert.deepEqual(evidence.cases.map(c => c.fsr_no), ['FSR-00005', 'FSR-00024'])
  assert.deepEqual(evidence.documents.map(d => [d.sha, d.page]), [[SHA, 45], [SHA, 46]])
  assert.equal(evidence.documents[0].label, 'F400 매뉴얼 p.2-31')
  assert.deepEqual(evidence.handlers, [{ fsr_no: 'FSR-00005', worker: 'EMP-0003', center: 'CENTER-003', branch: '천안직영센터' }])
})

test('evidence ignores unfinished, failed and malformed tool parts', () => {
  const evidence = evidenceFrom([
    part('search_cases', undefined, 'input-available'),
    part('search_manual', { ok: false, error: { code: 'database_unavailable' } }),
    part('search_cases', { results: [{ machine: 'no number' }] }),
    { type: 'text', text: 'x' }, null,
  ])
  assert.deepEqual(evidence, { cases: [], documents: [], handlers: [] })
})

test('the page address carries only the request number, a document hash and a page', () => {
  assert.equal(chatPageUrl('CLM-005', SHA, 45), `/api/v1/service-requests/CLM-005/chat/page?document_sha256=${SHA}&page=45`)
  for (const bad of [['x', SHA, 1], ['CLM-005', 'nope', 1], ['CLM-005', SHA, 0], ['CLM-005', SHA, 'a'], ['CLM-005', SHA + '/../', 1]]) {
    assert.throws(() => chatPageUrl(...bad))
  }
})

test('only the newest message is sent: the server keeps the history', () => {
  const messages = [{ id: '1', role: 'user' }, { id: '2', role: 'assistant' }, { id: '3', role: 'user', parts: [{ type: 'text', text: '질문' }] }]
  assert.deepEqual(transportBody({ id: 'chat', messages, trigger: 'submit-message' }), {
    id: 'chat', trigger: 'submit-message', messages: [messages[2]] })
})

test('the stored history splits one answer into several assistant messages: they read as one turn', () => {
  const user = { id: 'u1', role: 'user', parts: [{ type: 'text', text: '질문' }] }
  const toolMessage = { id: 'a1', role: 'assistant', parts: [part('lookup_case', { found: true })] }
  const textMessage = { id: 'a2', role: 'assistant', parts: [{ type: 'text', text: '답' }] }
  const next = { id: 'u2', role: 'user', parts: [{ type: 'text', text: '또' }] }
  const turns = groupTurns([user, toolMessage, textMessage, next])
  assert.deepEqual(turns.map(turn => [turn.role, turn.parts.length]), [['user', 1], ['assistant', 2], ['user', 1]])
  assert.equal(turns[1].id, 'a1')
  assert.deepEqual(groupTurns([]), [])
  assert.deepEqual(groupTurns(undefined), [])
})

test('a handler reads as one line and says so when nothing was recorded', () => {
  assert.equal(handlerLine({ fsr_no: 'FSR-00005', worker: 'EMP-0003', center: 'CENTER-003', branch: '천안직영센터' }),
    'FSR-00005 · 작업자 EMP-0003 · 천안직영센터 · CENTER-003')
  assert.equal(handlerLine({ fsr_no: 'FSR-00006', worker: '', center: '', branch: '' }), 'FSR-00006 · 담당 기록 없음')
  assert.equal(handlerLine({ fsr_no: 'FSR-00007', worker: '', center: 'CENTER-009', branch: '' }), 'FSR-00007 · 작업자 기록 없음 · CENTER-009')
})

test('a mail draft card says what state it is in and never claims a mail was sent unless the server did', () => {
  assert.equal(draftStateLabel('draft'), '초안 · 아직 보내지 않았습니다')
  assert.equal(draftStateLabel('sending'), '보내는 중')
  assert.equal(draftStateLabel('sent'), '발송됨')
  assert.equal(draftStateLabel('failed'), '발송 실패 · 다시 보낼 수 있습니다')
  assert.equal(draftStateLabel('cancelled'), '취소됨')
})

test('send and cancel addresses carry only the request number and a numeric draft id', () => {
  assert.equal(mailDraftUrl('CLM-005', 7, 'send'), '/service-requests/CLM-005/mail-drafts/7/send')
  assert.equal(mailDraftUrl('CLM-005', 7, 'cancel'), '/service-requests/CLM-005/mail-drafts/7/cancel')
  for (const bad of [['x', 7, 'send'], ['CLM-005', '7/../', 'send'], ['CLM-005', 0, 'send'], ['CLM-005', 7, 'delete']]) assert.throws(() => mailDraftUrl(...bad))
})
