import test from 'node:test'
import assert from 'node:assert/strict'
import { requestFor, customerEvents, evidencePageUrl } from './domain/actions.js'

const item = { id: 'CLM-005' }

test('every screen action maps to a server request with only user-chosen data', () => {
  const cases = [
    [{ type: 'REANALYZE', id: 'CLM-005' }, 'POST', '/service-requests/CLM-005/reanalysis', undefined, 'accepted'],
    [{ type: 'RESOLVE', id: 'CLM-005', note: '완료 안내' }, 'POST', '/service-requests/CLM-005/resolution', { note: '완료 안내' }, 'item'],
  ]
  for (const [action, method, path, body, result] of cases) {
    assert.deepEqual(requestFor(action, item), { method, path, body, result }, action.type)
  }
})

test('actor, time, owner and company are never sent by the browser', () => {
  const forged = { type: 'RESOLVE', id: 'CLM-005', note: '결과', by: 'someone', at: '2000-01-01', to: 'x', company: 'y' }
  assert.deepEqual(requestFor(forged, item), { method: 'POST', path: '/service-requests/CLM-005/resolution', body: { note: '결과' }, result: 'item' })
})

test('unknown actions and unsafe identifiers are rejected instead of being sent', () => {
  assert.throws(() => requestFor({ type: 'RESET', id: 'CLM-005' }, item), /지원하지 않는 작업/)
  assert.throws(() => requestFor({ type: 'ADD_COMMENT', id: 'CLM-005', kind: 'public', text: '안내' }, item), /지원하지 않는 작업/)  // notes and replies are gone
  assert.throws(() => requestFor({ type: 'RESOLVE', id: '../admin', note: 'x' }, item), /요청 번호/)
  for (const type of ['APPROVE', 'DECLINE', 'ASSIGN', 'TOGGLE_DEPT', 'EDIT_DRAFT', 'WORK_START', 'WORK_COMPLETE']) {
    assert.throws(() => requestFor({ type, id: 'CLM-005', workKey: 'SVC-005' }, item), /지원하지 않는 작업/, type)  // retired with the old workflow
  }
})

test('customer history shows only server-provided customer wording and never internal text', () => {
  const events = customerEvents({
    history: [{ at: '2026-11-14T01:00:00Z', text: '서비스 요청이 접수되었습니다.' }, { at: '2026-11-14T02:00:00Z', text: '처리를 시작했습니다.' }],
    comments: [{ id: '1', by: '', kind: 'public', text: '확인 중입니다.', at: '2026-11-14T03:00:00Z' }],
  })
  assert.deepEqual(events.map(event => [event.who, event.text]), [
    ['시스템', '처리를 시작했습니다.'], ['시스템', '서비스 요청이 접수되었습니다.']])
  assert.equal(events.filter(event => event.message).length, 0)
  assert.equal(customerEvents({ history: [] }).length, 0)
})

test('AI answers cannot be rated: those action types are not supported', () => {
  for (const type of ['RATE_ANALYSIS', 'CLEAR_RATING']) {
    assert.throws(() => requestFor({ type, id: 'CLM-005', rating: 'helpful' }, item), /지원하지 않는 작업/, type)
  }
})

test('the original-page address is built only from a request number and a citation id', () => {
  assert.equal(evidencePageUrl('CLM-005', 'E1'), '/api/v1/service-requests/CLM-005/evidence/E1/page')
  assert.equal(evidencePageUrl('CLM-005', 'E1', 2), '/api/v1/service-requests/CLM-005/evidence/E1/page?revision=2')
  for (const revision of [0, -1, 1.5, '2', '1&x=1']) assert.throws(() => evidencePageUrl('CLM-005', 'E1', revision), /올바르지 않은/)
  for (const [id, evidence] of [['CLM-5', 'E1'], ['../CLM-005', 'E1'], ['CLM-005', '../E1'], ['CLM-005', 'E1/page'], ['CLM-005', ''], ['CLM-005', 'e1']]) {
    assert.throws(() => evidencePageUrl(id, evidence), /올바르지 않은/, `${id} ${evidence}`)
  }
})

test('customers have no follow-up actions after filing: those action types are not supported at all', () => {
  for (const type of ['CUSTOMER_REPLY', 'CUSTOMER_CALLBACK', 'CUSTOMER_CLOSE_REQUEST']) {
    assert.throws(() => requestFor({ type, id: 'CLM-005', text: 'x', reason: 'y' }, item), /지원하지 않는 작업/, type)
  }
})
