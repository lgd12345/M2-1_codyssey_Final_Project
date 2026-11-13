import test from 'node:test'
import assert from 'node:assert/strict'
import { requestFor, customerEvents } from './domain/actions.js'

const item = { id: 'CLM-005', departments: [{ key: 'service', selected: true }, { key: 'sales', selected: false }] }

test('every screen action maps to a server request with only user-chosen data', () => {
  const cases = [
    [{ type: 'REANALYZE', id: 'CLM-005' }, 'POST', '/service-requests/CLM-005/reanalysis', undefined, 'accepted'],
    [{ type: 'ASSIGN', id: 'CLM-005' }, 'POST', '/service-requests/CLM-005/assignee', undefined, 'item'],
    [{ type: 'ADD_COMMENT', id: 'CLM-005', kind: 'public', text: '안내' }, 'POST', '/service-requests/CLM-005/comments', { kind: 'public', text: '안내' }, 'item'],
    [{ type: 'APPROVE', id: 'CLM-005' }, 'POST', '/service-requests/CLM-005/approval', undefined, 'item'],
    [{ type: 'DECLINE', id: 'CLM-005', reason: '근거 부족' }, 'POST', '/service-requests/CLM-005/decline', { reason: '근거 부족' }, 'item'],
    [{ type: 'EDIT_DRAFT', id: 'CLM-005', key: 'service', text: '새 초안' }, 'PATCH', '/service-requests/CLM-005/departments/service', { draft: '새 초안' }, 'item'],
    [{ type: 'RESET_DRAFT', id: 'CLM-005', key: 'service' }, 'PATCH', '/service-requests/CLM-005/departments/service', { reset: true }, 'item'],
    [{ type: 'WORK_ASSIGN', id: 'CLM-005', workKey: 'SVC-005' }, 'POST', '/service-requests/CLM-005/work/SVC-005/assignee', undefined, 'item'],
    [{ type: 'WORK_START', id: 'CLM-005', workKey: 'SVC-005' }, 'POST', '/service-requests/CLM-005/work/SVC-005/start', undefined, 'item'],
    [{ type: 'WORK_COMPLETE', id: 'CLM-005', workKey: 'SVC-005', result: { summary: '조치', hours: '2' } }, 'POST', '/service-requests/CLM-005/work/SVC-005/complete', { summary: '조치', hours: '2' }, 'item'],
    [{ type: 'RESOLVE', id: 'CLM-005', note: '완료 안내' }, 'POST', '/service-requests/CLM-005/resolution', { note: '완료 안내' }, 'item'],
    [{ type: 'CUSTOMER_REPLY', id: 'CLM-005', text: '답변' }, 'POST', '/service-requests/CLM-005/replies', { text: '답변' }, 'item'],
    [{ type: 'CUSTOMER_CALLBACK', id: 'CLM-005' }, 'POST', '/service-requests/CLM-005/callback', undefined, 'item'],
    [{ type: 'CUSTOMER_CLOSE_REQUEST', id: 'CLM-005', reason: '해결' }, 'POST', '/service-requests/CLM-005/close-request', { reason: '해결' }, 'item'],
  ]
  for (const [action, method, path, body, result] of cases) {
    assert.deepEqual(requestFor(action, item), { method, path, body, result }, action.type)
  }
})

test('department toggling sends the opposite of the stored selection, not a client-side guess', () => {
  assert.deepEqual(requestFor({ type: 'TOGGLE_DEPT', id: 'CLM-005', key: 'service' }, item).body, { selected: false })
  assert.deepEqual(requestFor({ type: 'TOGGLE_DEPT', id: 'CLM-005', key: 'sales' }, item).body, { selected: true })
  assert.throws(() => requestFor({ type: 'TOGGLE_DEPT', id: 'CLM-005', key: 'legal' }, item), /알 수 없는 부서/)
})

test('actor, time, owner and company are never sent by the browser', () => {
  const forged = { type: 'APPROVE', id: 'CLM-005', by: 'someone', at: '2000-01-01', to: 'x', company: 'y' }
  assert.deepEqual(requestFor(forged, item), { method: 'POST', path: '/service-requests/CLM-005/approval', body: undefined, result: 'item' })
  const comment = requestFor({ type: 'ADD_COMMENT', id: 'CLM-005', kind: 'internal', text: '메모', by: 'forged', at: 'x' }, item)
  assert.deepEqual(comment.body, { kind: 'internal', text: '메모' })
})

test('unknown actions and unsafe identifiers are rejected instead of being sent', () => {
  assert.throws(() => requestFor({ type: 'RESET', id: 'CLM-005' }, item), /지원하지 않는 작업/)
  assert.throws(() => requestFor({ type: 'APPROVE', id: '../admin' }, item), /요청 번호/)
  assert.throws(() => requestFor({ type: 'WORK_START', id: 'CLM-005', workKey: 'SVC-005/../x' }, item), /업무 번호/)
})

test('customer history shows only server-provided customer wording and never internal text', () => {
  const events = customerEvents({
    history: [{ at: '2026-11-14T01:00:00Z', text: '서비스 요청이 접수되었습니다.' }, { at: '2026-11-14T02:00:00Z', text: '담당 부서에서 처리를 시작했습니다.' }],
    comments: [{ id: '1', by: '', kind: 'public', text: '확인 중입니다.', at: '2026-11-14T03:00:00Z' }, { id: '2', by: '', kind: 'customer', text: '문의', at: '2026-11-14T04:00:00Z' }],
  })
  assert.deepEqual(events.map(event => [event.who, event.text]), [
    ['나', '문의'], ['서비스 담당자', '확인 중입니다.'], ['시스템', '담당 부서에서 처리를 시작했습니다.'], ['시스템', '서비스 요청이 접수되었습니다.']])
  assert.equal(events.filter(event => event.message).length, 2)
})
