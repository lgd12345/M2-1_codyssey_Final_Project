import assert from 'node:assert/strict'
import test from 'node:test'
import { ANALYSIS_STEPS, SCENARIOS } from './mock/data.js'
import { canApprove, canResolve, createInitialState, customerStatus, reducer, statusCounts, workItems } from './mock/store.js'

const AT = '2026-11-13T10:00:00'
const run = (state, ...actions) => actions.reduce(reducer, state)
const find = (state, id) => state.cases.find((c) => c.id === id)
const FREE_INTAKE = { company: 'A', machine: 'VMCT-03', serial: 'X', symptom: '기계에서 이상한 소리가 납니다.', alarm: '', occurred: '', type: '기술 문의', creator: '김현장 (A)' }

function finish(state, id) {
  let next = state
  for (let i = 0; i < ANALYSIS_STEPS.length; i += 1) next = reducer(next, { type: 'ADVANCE', id, at: AT })
  return next
}

function analyzed(sampleId) {
  const intake = sampleId ? { ...SCENARIOS[sampleId].intake, type: '기계 고장', creator: '김현장 (A)' } : FREE_INTAKE
  const state = reducer(createInitialState(), { type: 'CREATE', intake, sampleId, at: AT })
  const id = state.cases[0].id
  return { state: finish(state, id), id }
}

const approved = (sampleId) => {
  const { state, id } = analyzed(sampleId)
  return { state: reducer(state, { type: 'APPROVE', id, by: 'qa', at: AT }), id }
}

test('시연 시작 상태: 처리 중 1, 검토 대기 3, 추가 정보 필요 1', () => {
  assert.deepEqual(statusCounts(createInitialState().cases), { '분석 중': 0, '검토 대기': 3, '추가 정보 필요': 1, '처리 중': 1, '반려됨': 0, 종결: 0 })
})

test('새 요청은 분석 중으로 시작하고 단계가 끝나면 시나리오 결과로 바뀐다', () => {
  let state = reducer(createInitialState(), { type: 'CREATE', intake: SCENARIOS.s1.intake, sampleId: 's1', at: AT })
  const id = state.cases[0].id
  assert.equal(find(state, id).status, '분석 중')
  assert.equal(find(state, id).analysis, null)
  for (let i = 0; i < ANALYSIS_STEPS.length - 1; i += 1) state = reducer(state, { type: 'ADVANCE', id, at: AT })
  assert.equal(find(state, id).status, '분석 중')
  state = reducer(state, { type: 'ADVANCE', id, at: AT })
  assert.equal(find(state, id).status, '검토 대기')
  assert.deepEqual(find(state, id).departments.filter((d) => d.selected).map((d) => d.key), ['service'])
  assert.ok(find(state, id).analysis.steps.length > 0)
})

test('접수한 장비의 보증 정보가 요청에 붙는다', () => {
  const { state, id } = analyzed('s4')
  assert.equal(find(state, id).intake.asset.warranty, '보증 만료')
  assert.equal(find(createInitialState(), 'CLM-005').intake.asset.warranty, '보증 기간 내')
})

test('샘플 없이 직접 입력하면 근거 부족 시나리오로 분석한다', () => {
  const { state, id } = analyzed(null)
  const c = find(state, id)
  assert.equal(c.status, '추가 정보 필요')
  assert.equal(c.analysis.causes.length, 0)
  assert.equal(c.analysis.caseSearch, 'unavailable')
})

test('승인 전에는 연결 업무가 없고, 승인하면 선택한 부서만 현재 초안으로 생성된다', () => {
  const { state, id } = analyzed('s2')
  assert.deepEqual(find(state, id).linked, [])
  const edited = run(state, { type: 'EDIT_DRAFT', id, key: 'quality', text: '수정한 품질 초안' }, { type: 'TOGGLE_DEPT', id, key: 'sales' })
  const c = find(reducer(edited, { type: 'APPROVE', id, by: 'qa', at: AT }), id)
  assert.equal(c.status, '처리 중')
  assert.deepEqual(c.linked.map((l) => l.key), ['service', 'quality', 'sales'])
  assert.deepEqual(c.linked.map((l) => l.workKey), [`SVC-${id.slice(4)}`, `QLT-${id.slice(4)}`, `SAL-${id.slice(4)}`])
  assert.ok(c.linked.every((l) => l.status === '전달됨' && l.assignee === null))
  assert.equal(c.linked.find((l) => l.key === 'quality').content, '수정한 품질 초안')
  assert.equal(c.linked.find((l) => l.key === 'quality').edited, true)
  assert.equal(c.assignee, 'qa')
})

test('승인을 두 번 눌러도 연결 업무가 중복되지 않는다', () => {
  const { state, id } = approved('s1')
  const twice = reducer(state, { type: 'APPROVE', id, by: 'other', at: '2026-11-13T11:00:00' })
  assert.equal(find(twice, id).approval.by, 'qa')
  assert.equal(find(twice, id).linked.length, 1)
  assert.equal(find(twice, id).history.length, find(state, id).history.length)
})

test('승인 후에는 부서 선택과 초안을 바꿀 수 없다', () => {
  const { state, id } = approved('s1')
  const after = run(state, { type: 'TOGGLE_DEPT', id, key: 'sales' }, { type: 'EDIT_DRAFT', id, key: 'service', text: '변경' })
  assert.deepEqual(find(after, id).departments, find(state, id).departments)
})

test('부서를 모두 빼거나 선택한 초안이 비어 있으면 승인할 수 없다', () => {
  const { state, id } = analyzed('s1')
  assert.equal(canApprove(find(state, id)), true)
  const noDept = reducer(state, { type: 'TOGGLE_DEPT', id, key: 'service' })
  assert.equal(canApprove(find(noDept, id)), false)
  assert.equal(find(reducer(noDept, { type: 'APPROVE', id, by: 'qa', at: AT }), id).status, '검토 대기')
  assert.equal(canApprove(find(reducer(state, { type: 'EDIT_DRAFT', id, key: 'service', text: '  ' }), id)), false)
})

test('반려는 사유가 있어야 하고, 사유는 내부 메모로 남으며 연결 업무는 생기지 않는다', () => {
  const { state, id } = analyzed('s1')
  assert.equal(find(reducer(state, { type: 'DECLINE', id, by: 'qa', reason: '  ', at: AT }), id).status, '검토 대기')
  const declined = find(reducer(state, { type: 'DECLINE', id, by: 'qa', reason: '근거가 부족합니다', at: AT }), id)
  assert.equal(declined.status, '반려됨')
  assert.deepEqual(declined.linked, [])
  assert.equal(declined.comments.at(-1).kind, 'internal')
  assert.match(declined.comments.at(-1).text, /반려 사유: 근거가 부족합니다/)
})

test('반려된 건은 수정·승인할 수 없고 재분석하면 다시 분석한다', () => {
  const { state, id } = analyzed('s1')
  const declined = reducer(state, { type: 'DECLINE', id, by: 'qa', reason: '재검토', at: AT })
  const tried = run(declined, { type: 'TOGGLE_DEPT', id, key: 'sales' }, { type: 'APPROVE', id, by: 'qa', at: AT })
  assert.equal(find(tried, id).status, '반려됨')
  const again = reducer(declined, { type: 'REANALYZE', id, at: AT })
  assert.equal(find(again, id).status, '분석 중')
  assert.equal(find(finish(again, id), id).status, '검토 대기')
  assert.equal(find(again, id).revision, 2)
})

// ---- 승인 이후: 부서 처리 → 취합 → 종결 ----

test('시연 시작 상태의 CLM-001은 서비스 완료, 영업 진행 중이라 아직 종결할 수 없다', () => {
  const c = find(createInitialState(), 'CLM-001')
  assert.equal(c.status, '처리 중')
  assert.deepEqual(c.linked.map((l) => [l.workKey, l.status]), [['SVC-001', '완료'], ['SAL-001', '진행 중']])
  assert.equal(canResolve(c), false)
})

test('부서는 전달된 업무를 시작하고 결과를 입력해야 완료할 수 있다', () => {
  const { state, id } = approved('s1')
  const key = find(state, id).linked[0].workKey
  const noStart = reducer(state, { type: 'WORK_COMPLETE', id, workKey: key, by: '서비스팀', at: AT, result: { summary: '결과' } })
  assert.equal(find(noStart, id).linked[0].status, '전달됨')
  const started = reducer(state, { type: 'WORK_START', id, workKey: key, by: '서비스팀 박기사', at: AT })
  assert.equal(find(started, id).linked[0].status, '진행 중')
  assert.equal(find(started, id).linked[0].assignee, '서비스팀 박기사')
  const empty = reducer(started, { type: 'WORK_COMPLETE', id, workKey: key, by: '서비스팀', at: AT, result: { summary: '  ' } })
  assert.equal(find(empty, id).linked[0].status, '진행 중')
  const done = reducer(started, { type: 'WORK_COMPLETE', id, workKey: key, by: '서비스팀', at: AT, result: { summary: '센서 재조임', hours: '1.5' } })
  assert.deepEqual([find(done, id).linked[0].status, find(done, id).linked[0].result], ['완료', { summary: '센서 재조임', hours: '1.5' }])
})

test('모든 연결 업무가 완료되어야 종결할 수 있고, 종결하면 고객에게는 완료로 보인다', () => {
  const state = createInitialState()
  assert.equal(find(reducer(state, { type: 'RESOLVE', id: 'CLM-001', by: 'qa', at: AT }), 'CLM-001').status, '처리 중')
  const ready = run(state, { type: 'WORK_COMPLETE', id: 'CLM-001', workKey: 'SAL-001', by: '영업팀', at: AT, result: { summary: '고객에게 보증 만료 사실과 유상 수리 조건을 설명했습니다.' } })
  assert.equal(canResolve(find(ready, 'CLM-001')), true)
  const closed = find(reducer(ready, { type: 'RESOLVE', id: 'CLM-001', by: 'qa', note: '처리 완료', at: AT }), 'CLM-001')
  assert.equal(closed.status, '종결')
  assert.equal(closed.resolution.note, '처리 완료')
  assert.equal(customerStatus(closed), '완료')
})

test('부서 업무함에는 해당 부서가 받은 업무만 모인다', () => {
  const { cases } = createInitialState()
  assert.deepEqual(workItems(cases, 'sales').map((w) => w.workKey), ['SAL-001'])
  assert.deepEqual(workItems(cases, 'service').map((w) => w.workKey), ['SVC-001'])
  assert.deepEqual(workItems(cases, 'quality'), [])
})

test('고객 포털에는 내부 상태 대신 진행 단계만 보인다', () => {
  const view = (status) => customerStatus({ status })
  assert.deepEqual(['분석 중', '검토 대기', '반려됨', '추가 정보 필요', '처리 중', '종결'].map(view), ['접수됨', '확인 중', '확인 중', '정보 요청', '처리 중', '완료'])
})

// ---- 고객 행동 ----

test('고객이 정보를 추가하면 처리 중인 건에는 메시지만 남고 재분석되지 않는다', () => {
  const state = reducer(createInitialState(), { type: 'CUSTOMER_REPLY', id: 'CLM-001', text: '증상이 다시 나타났습니다', at: AT })
  assert.equal(find(state, 'CLM-001').status, '처리 중')
  assert.equal(find(state, 'CLM-001').comments.at(-1).kind, 'customer')
})

test('정보 요청 상태에서 고객 답변이 충분하면 새 시나리오로 재분석되고, 짧으면 그대로다', () => {
  const { state, id } = analyzed(null)
  assert.equal(find(reducer(state, { type: 'CUSTOMER_REPLY', id, text: '짧음', at: AT }), id).scenarioId, 's5')
  const replied = reducer(state, { type: 'CUSTOMER_REPLY', id, text: '주축 저속 회전 때 갈리는 소리가 납니다', at: AT })
  assert.equal(find(replied, id).status, '분석 중')
  const done = find(finish(replied, id), id)
  assert.deepEqual([done.status, done.scenarioId], ['검토 대기', 's5b'])
  assert.match(done.intake.symptom, /\[추가 정보\]/)
})

test('고객의 콜백 요청과 종결 요청이 기록되고, 종결 요청은 사유가 있어야 한다', () => {
  let state = reducer(createInitialState(), { type: 'CUSTOMER_CALLBACK', id: 'CLM-005', at: AT })
  assert.equal(find(state, 'CLM-005').comments.at(-1).text, '콜백을 요청했습니다.')
  state = reducer(state, { type: 'CUSTOMER_CLOSE_REQUEST', id: 'CLM-005', reason: '  ', at: AT })
  assert.equal(find(state, 'CLM-005').closeRequested, false)
  state = reducer(state, { type: 'CUSTOMER_CLOSE_REQUEST', id: 'CLM-005', reason: '자체 해결했습니다', at: AT })
  assert.equal(find(state, 'CLM-005').closeRequested, true)
  assert.match(find(state, 'CLM-005').comments.at(-1).text, /\[종결 요청\] 자체 해결했습니다/)
})

test('종결된 건에는 고객 행동이 더 이상 적용되지 않는다', () => {
  let state = run(createInitialState(), { type: 'WORK_COMPLETE', id: 'CLM-001', workKey: 'SAL-001', by: '영업팀', at: AT, result: { summary: '설명 완료' } }, { type: 'RESOLVE', id: 'CLM-001', by: 'qa', at: AT })
  const before = find(state, 'CLM-001').comments.length
  state = run(state, { type: 'CUSTOMER_REPLY', id: 'CLM-001', text: '추가 문의', at: AT }, { type: 'CUSTOMER_CALLBACK', id: 'CLM-001', at: AT })
  assert.equal(find(state, 'CLM-001').comments.length, before)
})

// ---- 공통 ----

test('내부 메모를 남기고 빈 내용은 무시한다', () => {
  const { state, id } = analyzed('s1')
  const next = run(state, { type: 'ADD_COMMENT', id, kind: 'internal', text: '  메모  ', by: 'qa', at: AT }, { type: 'ADD_COMMENT', id, kind: 'public', text: '   ', by: 'qa', at: AT })
  assert.deepEqual(find(next, id).comments.map((c) => [c.kind, c.text]), [['internal', '메모']])
})

test('담당자 지정은 비어 있을 때만 된다', () => {
  const { state, id } = analyzed('s1')
  const once = reducer(state, { type: 'ASSIGN', id, to: 'a', at: AT })
  assert.equal(find(reducer(once, { type: 'ASSIGN', id, to: 'b', at: AT }), id).assignee, 'a')
})

test('초안을 AI 원본으로 되돌릴 수 있다', () => {
  const { state, id } = analyzed('s1')
  const reset = run(state, { type: 'EDIT_DRAFT', id, key: 'service', text: '다른 내용' }, { type: 'RESET_DRAFT', id, key: 'service' })
  const d = find(reset, id).departments.find((x) => x.key === 'service')
  assert.equal(d.draft, d.aiDraft)
})

test('분석 중이거나 처리 중인 건은 재분석되지 않는다', () => {
  const state = reducer(createInitialState(), { type: 'CREATE', intake: SCENARIOS.s1.intake, sampleId: 's1', at: AT })
  assert.equal(find(reducer(state, { type: 'REANALYZE', id: state.cases[0].id, at: AT }), state.cases[0].id).revision, 1)
  assert.equal(find(reducer(createInitialState(), { type: 'REANALYZE', id: 'CLM-001', at: AT }), 'CLM-001').status, '처리 중')
})

test('접수 번호는 계속 증가하고 시연 초기화는 처음 상태로 되돌린다', () => {
  const state = run(createInitialState(), { type: 'CREATE', intake: SCENARIOS.s1.intake, sampleId: 's1', at: AT }, { type: 'CREATE', intake: SCENARIOS.s1.intake, sampleId: 's1', at: AT })
  assert.deepEqual(state.cases.slice(0, 2).map((c) => c.id), ['CLM-007', 'CLM-006'])
  assert.deepEqual(reducer(state, { type: 'RESET' }), createInitialState())
})
