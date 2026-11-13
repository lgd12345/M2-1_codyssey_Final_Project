import { ANALYSIS_STEPS, DEPARTMENTS, SCENARIOS } from './data.js'
import { DEPT_PREFIX, META } from './meta.js'

// 순수 상태 로직. 시간(at)과 사용자(by)는 액션으로 받아 reducer가 항상 같은 결과를 내도록 한다.

export const STATUSES = ['분석 중', '검토 대기', '추가 정보 필요', '승인됨', '반려됨']
const EDITABLE = ['검토 대기', '추가 정보 필요'] // 부서·초안 수정, 승인/반려가 가능한 상태
const REANALYZABLE = ['검토 대기', '추가 정보 필요', '반려됨']

const deptName = (key) => DEPARTMENTS.find((d) => d.key === key)?.name ?? key
const fallbackDraft = (key, title) => `[${deptName(key)} 요청 · AI 초안, 검토 필요]\n- 건명: ${title}\n- 요청 내용을 작성해 주세요.`
let commentSeq = 0
const comment = (by, kind, text, at) => ({ id: `c${++commentSeq}`, by, kind, text, at })

function buildDepartments(scenario) {
  return DEPARTMENTS.map(({ key }) => {
    const spec = scenario.departments[key]
    const draft = spec.draft || fallbackDraft(key, scenario.title)
    return { key, aiSelected: spec.selected, selected: spec.selected, reason: spec.reason, aiDraft: draft, draft }
  })
}

function buildAnalysis(scenario) {
  const meta = META[scenario.id]
  return {
    summary: scenario.summary, causes: scenario.causes, questions: scenario.questions, evidence: scenario.evidence,
    caseSearch: scenario.caseSearch, stepResults: scenario.stepResults, steps: meta.steps, parts: meta.parts,
  }
}

function completeAnalysis(c, at) {
  const scenario = SCENARIOS[c.scenarioId]
  return {
    ...c, status: scenario.status, stepsDone: ANALYSIS_STEPS.length,
    analysis: buildAnalysis(scenario), departments: buildDepartments(scenario),
    history: [...c.history, { at, text: scenario.status === '추가 정보 필요' ? '분석 완료 · 근거 부족, 추가 정보 필요' : '분석 완료 · 검토 대기' }],
  }
}

const blankCase = (id, title, intake, scenarioId, at) => ({
  id, title, intake, scenarioId, status: '분석 중', createdAt: at, stepsDone: 0, analysis: null, departments: [],
  approval: null, linked: [], comments: [], assignee: null, revision: 1, history: [{ at, text: '접수' }],
})

function seedCase(n, scenarioId, at, extra = {}) {
  const scenario = SCENARIOS[scenarioId]
  const intake = { ...scenario.intake, type: META[scenarioId].type, creator: META[scenarioId].creator,
    contact: { name: META[scenarioId].creator.split(' ')[0], phone: '', email: '' } }
  const id = `CLM-${String(n).padStart(3, '0')}`
  return { ...completeAnalysis(blankCase(id, scenario.title, intake, scenarioId, at), at), ...extra }
}

export function createInitialState() {
  commentSeq = 0
  const sealed = approveCase(
    { ...seedCase(1, 's4', '2026-11-10T09:12:00'),
      comments: [comment('quality-demo', 'internal', '고객이 무상 처리를 요구하고 있음. 이전 수리 기록 확인 후 영업 대응과 함께 전달.', '2026-11-10T10:55:00')] },
    'quality-demo', '2026-11-10T11:40:00')
  return {
    nextNumber: 6,
    cases: [
      seedCase(5, 's1', '2026-11-13T09:05:00'),
      seedCase(4, 's5', '2026-11-12T16:30:00', {
        assignee: 'quality-demo',
        comments: [comment('quality-demo', 'public', '안녕하세요. 소음이 나는 위치와 어떤 동작 중에 발생하는지 알려 주시면 확인하겠습니다.', '2026-11-12T16:45:00')],
      }),
      seedCase(3, 's3', '2026-11-12T14:20:00'),
      seedCase(2, 's2', '2026-11-11T10:48:00'),
      sealed,
    ],
  }
}

export const isEditable = (c) => EDITABLE.includes(c.status)
export const isReviewable = isEditable
export const canReanalyze = (c) => REANALYZABLE.includes(c.status)

export function canApprove(c) {
  if (!isEditable(c) || !c.analysis) return false
  const selected = c.departments.filter((d) => d.selected)
  return selected.length > 0 && selected.every((d) => d.draft.trim().length > 0)
}

export const isEdited = (d) => d.draft !== d.aiDraft

export const statusCounts = (cases) =>
  Object.fromEntries(STATUSES.map((s) => [s, cases.filter((c) => c.status === s).length]))

function approveCase(c, by, at) {
  // 이미 승인된 건을 다시 승인해도 연결 업무가 중복 생성되지 않는다.
  if (c.status === '승인됨' || !canApprove(c)) return c
  const number = c.id.replace('CLM-', '')
  const delivered = c.departments.filter((d) => d.selected)
    .map((d) => ({ key: d.key, name: deptName(d.key), content: d.draft, edited: isEdited(d) }))
  const linked = delivered.map((d) => ({ ...d, workKey: `${DEPT_PREFIX[d.key]}-${number}`, status: '전달됨' }))
  return {
    ...c, status: '승인됨', approval: { by, at, delivered }, linked, assignee: c.assignee ?? by,
    history: [...c.history, { at, text: `${by} 승인 · ${delivered.map((d) => d.name).join(', ')} 연결 업무 생성` }],
  }
}

function reanalyze(c, note, at, label) {
  if (!canReanalyze(c)) return c
  const text = (note || '').trim()
  const supplemented = c.scenarioId === 's5' && text.length >= 10
  return {
    ...c, status: '분석 중', stepsDone: 0, analysis: null, departments: [], approval: null, linked: [], revision: c.revision + 1,
    scenarioId: supplemented ? 's5b' : c.scenarioId,
    title: supplemented ? SCENARIOS.s5b.title : c.title,
    intake: supplemented ? { ...c.intake, symptom: `${c.intake.symptom}\n[추가 정보] ${text}` } : c.intake,
    history: [...c.history, { at, text: supplemented ? '고객 추가 정보 반영 · 재분석' : label }],
  }
}

const mapCase = (state, id, fn) => ({ ...state, cases: state.cases.map((c) => (c.id === id ? fn(c) : c)) })
const mapDept = (c, key, fn) => ({ ...c, departments: c.departments.map((d) => (d.key === key ? fn(d) : d)) })

export function reducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return createInitialState()
    case 'CREATE': {
      const { intake, sampleId, at } = action
      const scenarioId = sampleId && SCENARIOS[sampleId] ? sampleId : 's5'
      const scenario = SCENARIOS[scenarioId]
      const id = `CLM-${String(state.nextNumber).padStart(3, '0')}`
      const title = sampleId ? scenario.title : (intake.symptom.trim().slice(0, 30) || scenario.title)
      return { nextNumber: state.nextNumber + 1, cases: [blankCase(id, title, intake, scenarioId, at), ...state.cases] }
    }
    case 'ADVANCE':
      return mapCase(state, action.id, (c) => {
        if (c.status !== '분석 중') return c
        const done = c.stepsDone + 1
        return done >= ANALYSIS_STEPS.length ? completeAnalysis(c, action.at) : { ...c, stepsDone: done }
      })
    case 'REANALYZE':
      return mapCase(state, action.id, (c) => reanalyze(c, '', action.at, '재분석 요청'))
    case 'CUSTOMER_REPLY': // 시연용: 고객이 추가 정보를 답한 상황을 만든다.
      return mapCase(state, action.id, (c) => c.status !== '추가 정보 필요' ? c
        : reanalyze({ ...c, comments: [...c.comments, comment(c.intake.creator, 'customer', action.text, action.at)] }, action.text, action.at, '고객 답변 · 재분석'))
    case 'TOGGLE_DEPT':
      return mapCase(state, action.id, (c) => !isEditable(c) ? c : mapDept(c, action.key, (d) => ({ ...d, selected: !d.selected })))
    case 'EDIT_DRAFT':
      return mapCase(state, action.id, (c) => !isEditable(c) ? c : mapDept(c, action.key, (d) => ({ ...d, draft: action.text })))
    case 'RESET_DRAFT':
      return mapCase(state, action.id, (c) => !isEditable(c) ? c : mapDept(c, action.key, (d) => ({ ...d, draft: d.aiDraft })))
    case 'ASSIGN':
      return mapCase(state, action.id, (c) => c.assignee ? c
        : { ...c, assignee: action.to, history: [...c.history, { at: action.at, text: `${action.to} 담당자로 지정` }] })
    case 'ADD_COMMENT': {
      const text = (action.text || '').trim()
      if (!text) return state
      return mapCase(state, action.id, (c) => ({ ...c, comments: [...c.comments, comment(action.by, action.kind, text, action.at)] }))
    }
    case 'APPROVE':
      return mapCase(state, action.id, (c) => approveCase(c, action.by, action.at))
    case 'DECLINE':
      return mapCase(state, action.id, (c) => {
        const reason = (action.reason || '').trim()
        if (!isEditable(c) || !reason) return c
        return {
          ...c, status: '반려됨', comments: [...c.comments, comment(action.by, 'internal', `반려 사유: ${reason}`, action.at)],
          history: [...c.history, { at: action.at, text: `${action.by} 반려` }],
        }
      })
    default:
      return state
  }
}
