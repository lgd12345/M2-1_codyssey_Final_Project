import assert from 'node:assert/strict'
import test from 'node:test'
import { ANALYSIS_STEPS, SCENARIOS } from './mock/data.js'
import { canApprove, createInitialState, reducer, statusCounts } from './mock/store.js'

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

test('시연 시작 상태: 승인됨 1, 검토 대기 3, 추가 정보 필요 1', () => {
  assert.deepEqual(statusCounts(createInitialState().cases), { '분석 중': 0, '검토 대기': 3, '추가 정보 필요': 1, '승인됨': 1, '반려됨': 0 })
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
  assert.equal(c.status, '승인됨')
  assert.deepEqual(c.linked.map((l) => l.key), ['service', 'quality', 'sales'])
  assert.deepEqual(c.linked.map((l) => l.workKey), [`SVC-${id.slice(4)}`, `QLT-${id.slice(4)}`, `SAL-${id.slice(4)}`])
  assert.equal(c.linked.find((l) => l.key === 'quality').content, '수정한 품질 초안')
  assert.equal(c.linked.find((l) => l.key === 'quality').edited, true)
  assert.equal(c.assignee, 'qa')
})

test('승인을 두 번 눌러도 연결 업무가 중복되지 않는다', () => {
  const { state, id } = analyzed('s1')
  const once = reducer(state, { type: 'APPROVE', id, by: 'qa', at: AT })
  const twice = reducer(once, { type: 'APPROVE', id, by: 'other', at: '2026-11-13T11:00:00' })
  assert.equal(find(twice, id).approval.by, 'qa')
  assert.equal(find(twice, id).linked.length, 1)
  assert.equal(find(twice, id).history.length, find(once, id).history.length)
})

test('승인 후에는 부서 선택과 초안을 바꿀 수 없다', () => {
  const { state, id } = analyzed('s1')
  const approved = reducer(state, { type: 'APPROVE', id, by: 'qa', at: AT })
  const after = run(approved, { type: 'TOGGLE_DEPT', id, key: 'sales' }, { type: 'EDIT_DRAFT', id, key: 'service', text: '변경' })
  assert.deepEqual(find(after, id).departments, find(approved, id).departments)
})

test('부서를 모두 빼거나 선택한 초안이 비어 있으면 승인할 수 없다', () => {
  const { state, id } = analyzed('s1')
  assert.equal(canApprove(find(state, id)), true)
  const noDept = reducer(state, { type: 'TOGGLE_DEPT', id, key: 'service' })
  assert.equal(canApprove(find(noDept, id)), false)
  assert.equal(find(reducer(noDept, { type: 'APPROVE', id, by: 'qa', at: AT }), id).status, '검토 대기')
  assert.equal(canApprove(find(reducer(state, { type: 'EDIT_DRAFT', id, key: 'service', text: '  ' }), id)), false)
})

test('반려는 사유가 있어야 하고, 사유는 내부 메모로 남으며 승인 없이 연결 업무는 생기지 않는다', () => {
  const { state, id } = analyzed('s1')
  assert.equal(find(reducer(state, { type: 'DECLINE', id, by: 'qa', reason: '  ', at: AT }), id).status, '검토 대기')
  const declined = find(reducer(state, { type: 'DECLINE', id, by: 'qa', reason: '근거가 부족합니다', at: AT }), id)
  assert.equal(declined.status, '반려됨')
  assert.deepEqual(declined.linked, [])
  const note = declined.comments.at(-1)
  assert.equal(note.kind, 'internal')
  assert.match(note.text, /반려 사유: 근거가 부족합니다/)
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

test('내부 메모와 고객 답변을 남기고 빈 내용은 무시한다', () => {
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

test('고객 답변이 충분하면 근거 부족 건이 새 시나리오로 재분석되고, 짧으면 그대로다', () => {
  const { state, id } = analyzed(null)
  const short = reducer(state, { type: 'CUSTOMER_REPLY', id, text: '짧음', at: AT })
  assert.equal(find(short, id).scenarioId, 's5')
  const replied = reducer(state, { type: 'CUSTOMER_REPLY', id, text: '주축 저속 회전 때 갈리는 소리가 납니다', at: AT })
  assert.equal(find(replied, id).status, '분석 중')
  assert.equal(find(replied, id).comments.at(-1).kind, 'customer')
  const done = find(finish(replied, id), id)
  assert.equal(done.status, '검토 대기')
  assert.equal(done.scenarioId, 's5b')
  assert.match(done.intake.symptom, /\[추가 정보\]/)
})

test('분석 중이거나 승인된 건은 재분석·고객 답변이 적용되지 않는다', () => {
  let state = reducer(createInitialState(), { type: 'CREATE', intake: SCENARIOS.s1.intake, sampleId: 's1', at: AT })
  const running = state.cases[0]
  assert.equal(find(reducer(state, { type: 'REANALYZE', id: running.id, at: AT }), running.id).revision, 1)
  state = createInitialState()
  assert.equal(find(reducer(state, { type: 'REANALYZE', id: 'CLM-001', at: AT }), 'CLM-001').status, '승인됨')
  assert.equal(find(reducer(state, { type: 'CUSTOMER_REPLY', id: 'CLM-001', text: '충분히 긴 답변입니다', at: AT }), 'CLM-001').status, '승인됨')
})

test('접수 번호는 계속 증가하고 시연 초기화는 처음 상태로 되돌린다', () => {
  const state = run(createInitialState(), { type: 'CREATE', intake: SCENARIOS.s1.intake, sampleId: 's1', at: AT }, { type: 'CREATE', intake: SCENARIOS.s1.intake, sampleId: 's1', at: AT })
  assert.deepEqual(state.cases.slice(0, 2).map((c) => c.id), ['CLM-007', 'CLM-006'])
  assert.deepEqual(reducer(state, { type: 'RESET' }), createInitialState())
})
