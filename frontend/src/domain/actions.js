// Maps screen actions to server requests. The browser chooses only the action and user-entered text;
// actors, times, identifiers of created records and company scope are decided by the server.
const ID = /^CLM-\d{3,19}$/
const WORK = /^(SVC|QLT|PRT|SAL)-\d{3,19}$/
const KEYS = ['service', 'quality', 'parts', 'sales']
const EVIDENCE = /^E\d{1,3}$/
const RATINGS = ['helpful', 'not_helpful']

export function requestFor(action, item) {
  if (!ID.test(action.id ?? '')) throw new Error('올바르지 않은 요청 번호입니다.')
  const base = `/service-requests/${action.id}`
  const work = () => {
    if (!WORK.test(action.workKey ?? '')) throw new Error('올바르지 않은 업무 번호입니다.')
    return `${base}/work/${action.workKey}`
  }
  const dept = () => {
    if (!KEYS.includes(action.key)) throw new Error('알 수 없는 부서입니다.')
    return `${base}/departments/${action.key}`
  }
  const post = (path, body, result = 'item') => ({ method: 'POST', path, body, result })
  switch (action.type) {
    case 'REANALYZE': return post(`${base}/reanalysis`, undefined, 'accepted')
    case 'ASSIGN': return post(`${base}/assignee`)
    case 'ADD_COMMENT': return post(`${base}/comments`, { kind: action.kind, text: action.text })
    case 'APPROVE': return post(`${base}/approval`)
    case 'DECLINE': return post(`${base}/decline`, { reason: action.reason })
    case 'TOGGLE_DEPT': {
      const current = item?.departments?.find(department => department.key === action.key)
      if (!current) throw new Error('알 수 없는 부서입니다.')
      return { method: 'PATCH', path: dept(), body: { selected: !current.selected }, result: 'item' }
    }
    case 'EDIT_DRAFT': return { method: 'PATCH', path: dept(), body: { draft: action.text }, result: 'item' }
    case 'RESET_DRAFT': return { method: 'PATCH', path: dept(), body: { reset: true }, result: 'item' }
    case 'WORK_ASSIGN': return post(`${work()}/assignee`)
    case 'WORK_START': return post(`${work()}/start`)
    case 'WORK_COMPLETE': return post(`${work()}/complete`, { summary: action.result?.summary, hours: action.result?.hours ?? '' })
    case 'RESOLVE': return post(`${base}/resolution`, { note: action.note ?? '' })
    case 'RATE_ANALYSIS': {
      if (!RATINGS.includes(action.rating)) throw new Error('올바르지 않은 평가입니다.')
      return { method: 'PUT', path: `${base}/analysis/feedback`, body: { rating: action.rating }, result: 'item' }
    }
    case 'CLEAR_RATING': return { method: 'DELETE', path: `${base}/analysis/feedback`, body: undefined, result: 'item' }
    case 'CUSTOMER_REPLY': return post(`${base}/replies`, { text: action.text })
    case 'CUSTOMER_CALLBACK': return post(`${base}/callback`)
    case 'CUSTOMER_CLOSE_REQUEST': return post(`${base}/close-request`, { reason: action.reason })
    default: throw new Error('지원하지 않는 작업입니다.')
  }
}

// Original page of a manual citation. Only a request number and a citation id go into the address; the server
// decides which document page that is and whether this person may open it.
export function evidencePageUrl(id, evidenceId) {
  if (!ID.test(id ?? '') || !EVIDENCE.test(evidenceId ?? '')) throw new Error('올바르지 않은 원본 페이지 주소입니다.')
  return `/api/v1/service-requests/${id}/evidence/${evidenceId}/page`
}

// Ratings are visible to operators only; each person sees their own as pressed.
export const myRating = (analysis, me) => analysis?.feedback?.ratings?.find(rating => rating.by === me)?.rating ?? null

// The server already filtered history and comments to customer-safe content and wording.
export function customerEvents(item) {
  const history = item.history.map((entry, index) => ({ id: `h${index}`, at: entry.at, who: '시스템', text: entry.text }))
  const comments = item.comments.map(comment => ({
    id: comment.id, at: comment.at, who: comment.kind === 'customer' ? '나' : '서비스 담당자', text: comment.text, message: true,
  }))
  return [...history, ...comments].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0))
}
