import { ANALYSIS_STEPS, DEPARTMENTS, SCENARIOS } from './data.js'
import { ASSETS, DEPT_PREFIX, META } from './meta.js'

// 순수 상태 로직. 시간(at)과 사용자(by)는 액션으로 받아 reducer가 항상 같은 결과를 내도록 한다.
//
// 처리 흐름(조사 근거: Jira 연결 업무, 부서별 처리, 원본 요청에서 결과 확인 후 종결):
//   접수 → 분석 중 → 검토 대기 → (승인) 처리 중 → 모든 연결 업무 완료 → (품질 담당자 확인) 종결
//   분석 결과 근거가 부족하면 추가 정보 필요(고객 답변 대기), 검토에서 반려될 수 있다.

export const STATUSES = ['분석 중', '검토 대기', '추가 정보 필요', '처리 중', '반려됨', '종결']
export const WORK_STATUSES = ['전달됨', '진행 중', '완료']
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
  approval: null, linked: [], comments: [], assignee: null, resolution: null, closeRequested: false,
  revision: 1, history: [{ at, text: '접수' }],
})

function seedCase(n, scenarioId, at, extra = {}) {
  const scenario = SCENARIOS[scenarioId]
  const intake = { ...scenario.intake, type: META[scenarioId].type, creator: META[scenarioId].creator,
    contact: { name: META[scenarioId].creator.split(' ')[0], phone: '', email: '' }, asset: ASSETS[scenario.intake.serial] ?? null }
  const id = `CLM-${String(n).padStart(3, '0')}`
  return { ...completeAnalysis(blankCase(id, scenario.title, intake, scenarioId, at), at), ...extra }
}

export function createInitialState() {
  commentSeq = 0
  // CLM-001: 승인 후 부서 처리가 진행 중인 건. 서비스는 완료, 영업은 진행 중이다(처리 → 취합 → 종결 흐름을 바로 볼 수 있다).
  let processing = approveCase(
    { ...seedCase(1, 's4', '2026-11-10T09:12:00'),
      comments: [
        comment('quality-demo', 'internal', '고객이 무상 처리를 요구하고 있음. 보증 만료 건이라 영업 대응과 함께 전달.', '2026-11-10T10:55:00'),
        comment('quality-demo', 'public', '안녕하세요. 접수하신 건을 확인했습니다. 점검 결과를 확인하는 대로 안내드리겠습니다.', '2026-11-10T11:45:00'),
      ] },
    'quality-demo', '2026-11-10T11:40:00')
  processing = startWork(processing, 'SVC-001', '서비스팀 박기사', '2026-11-10T13:00:00')
  processing = completeWork(processing, 'SVC-001', '서비스팀 박기사', '2026-11-11T10:20:00',
    { summary: '슬라이드 커버 체결부 실링 재작업 후 누유 해소를 확인했습니다. 이전 수리 부위와 같은 위치였습니다.', hours: '2' })
  processing = startWork(processing, 'SAL-001', '영업팀 한영업', '2026-11-11T09:30:00')
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
      processing,
    ],
  }
}

export const isEditable = (c) => EDITABLE.includes(c.status)
export const isReviewable = isEditable
export const canReanalyze = (c) => REANALYZABLE.includes(c.status)
export const allWorkDone = (c) => c.linked.length > 0 && c.linked.every((l) => l.status === '완료')
export const canResolve = (c) => c.status === '처리 중' && allWorkDone(c)

export function canApprove(c) {
  if (!isEditable(c) || !c.analysis) return false
  const selected = c.departments.filter((d) => d.selected)
  return selected.length > 0 && selected.every((d) => d.draft.trim().length > 0)
}

export const isEdited = (d) => d.draft !== d.aiDraft

export const statusCounts = (cases) =>
  Object.fromEntries(STATUSES.map((s) => [s, cases.filter((c) => c.status === s).length]))

// 고객 포털에는 내부 상태 대신 고객이 이해하는 진행 단계만 보여 준다(AI 분석·내부 메모·초안은 숨긴다).
export const CUSTOMER_STATUS = { '분석 중': '접수됨', '검토 대기': '확인 중', '반려됨': '확인 중', '추가 정보 필요': '정보 요청', '처리 중': '처리 중', '종결': '완료' }
export const customerStatus = (c) => CUSTOMER_STATUS[c.status] ?? c.status

// 부서 업무함: 모든 요청의 연결 업무 중 해당 부서가 받은 것만 모은다.
export function workItems(cases, deptKey) {
  const name = deptName(deptKey)
  return cases.flatMap((c) => c.linked.filter((l) => l.name === name).map((l) => ({ ...l, caseId: c.id, caseTitle: c.title, intake: c.intake, caseStatus: c.status, createdAt: c.approval.at })))
}

function approveCase(c, by, at) {
  // 이미 승인된 건을 다시 승인해도 연결 업무가 중복 생성되지 않는다.
  if (c.status === '처리 중' || !canApprove(c)) return c
  const number = c.id.replace('CLM-', '')
  const delivered = c.departments.filter((d) => d.selected)
    .map((d) => ({ key: d.key, name: deptName(d.key), content: d.draft, edited: isEdited(d) }))
  const linked = delivered.map((d) => ({ ...d, workKey: `${DEPT_PREFIX[d.key]}-${number}`, status: '전달됨', assignee: null, result: null, startedAt: null, doneAt: null }))
  return {
    ...c, status: '처리 중', approval: { by, at, delivered }, linked, assignee: c.assignee ?? by,
    history: [...c.history, { at, text: `${by} 승인 · ${delivered.map((d) => d.name).join(', ')} 연결 업무 생성` }],
  }
}

const mapLinked = (c, workKey, fn) => ({ ...c, linked: c.linked.map((l) => (l.workKey === workKey ? fn(l) : l)) })

function startWork(c, workKey, by, at) {
  const item = c.linked.find((l) => l.workKey === workKey)
  if (c.status !== '처리 중' || !item || item.status !== '전달됨') return c
  return { ...mapLinked(c, workKey, (l) => ({ ...l, status: '진행 중', assignee: l.assignee ?? by, startedAt: at })),
    history: [...c.history, { at, text: `${workKey} 진행 시작 · ${by}` }] }
}

function completeWork(c, workKey, by, at, result) {
  const item = c.linked.find((l) => l.workKey === workKey)
  const summary = (result?.summary || '').trim()
  if (c.status !== '처리 중' || !item || item.status !== '진행 중' || !summary) return c
  return { ...mapLinked(c, workKey, (l) => ({ ...l, status: '완료', doneAt: at, result: { summary, hours: (result.hours || '').trim() } })),
    history: [...c.history, { at, text: `${workKey} 처리 완료 · ${by}` }] }
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
const addComment = (c, by, kind, text, at) => ({ ...c, comments: [...c.comments, comment(by, kind, text, at)] })

export function reducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return createInitialState()
    case 'CREATE': {
      const { sampleId, at } = action
      const scenarioId = sampleId && SCENARIOS[sampleId] ? sampleId : 's5'
      const scenario = SCENARIOS[scenarioId]
      const intake = { ...action.intake, asset: ASSETS[action.intake.serial] ?? null }
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
    case 'CUSTOMER_REPLY': // 고객이 정보를 추가한다. 정보 요청 상태이면 답변을 반영해 재분석한다.
      return mapCase(state, action.id, (c) => {
        const text = (action.text || '').trim()
        if (!text || c.status === '종결') return c
        const withMsg = addComment(c, c.intake.creator, 'customer', text, action.at)
        return c.status === '추가 정보 필요' ? reanalyze(withMsg, text, action.at, '고객 답변 · 재분석') : withMsg
      })
    case 'CUSTOMER_CALLBACK':
      return mapCase(state, action.id, (c) => c.status === '종결' ? c : addComment({ ...c, history: [...c.history, { at: action.at, text: '고객 콜백 요청' }] }, c.intake.creator, 'customer', '콜백을 요청했습니다.', action.at))
    case 'CUSTOMER_CLOSE_REQUEST':
      return mapCase(state, action.id, (c) => {
        const reason = (action.reason || '').trim()
        if (c.status === '종결' || !reason) return c
        return addComment({ ...c, closeRequested: true, history: [...c.history, { at: action.at, text: '고객 종결 요청' }] }, c.intake.creator, 'customer', `[종결 요청] ${reason}`, action.at)
      })
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
      return mapCase(state, action.id, (c) => addComment(c, action.by, action.kind, text, action.at))
    }
    case 'APPROVE':
      return mapCase(state, action.id, (c) => approveCase(c, action.by, action.at))
    case 'DECLINE':
      return mapCase(state, action.id, (c) => {
        const reason = (action.reason || '').trim()
        if (!isEditable(c) || !reason) return c
        return {
          ...addComment(c, action.by, 'internal', `반려 사유: ${reason}`, action.at), status: '반려됨',
          history: [...c.history, { at: action.at, text: `${action.by} 반려` }],
        }
      })
    case 'WORK_ASSIGN':
      return mapCase(state, action.id, (c) => c.status !== '처리 중' ? c
        : mapLinked(c, action.workKey, (l) => (l.assignee || l.status === '완료' ? l : { ...l, assignee: action.to })))
    case 'WORK_START':
      return mapCase(state, action.id, (c) => startWork(c, action.workKey, action.by, action.at))
    case 'WORK_COMPLETE':
      return mapCase(state, action.id, (c) => completeWork(c, action.workKey, action.by, action.at, action.result))
    case 'RESOLVE':
      // 모든 연결 업무가 완료되어야 하고, 종결은 품질 담당자가 결과를 확인한 뒤에 한다.
      return mapCase(state, action.id, (c) => !canResolve(c) ? c : {
        ...c, status: '종결', resolution: { by: action.by, at: action.at, note: (action.note || '').trim() },
        history: [...c.history, { at: action.at, text: `${action.by} 종결` }],
      })
    default:
      return state
  }
}
