// Maps screen actions to server requests. The browser chooses only the action and user-entered text;
// actors, times, identifiers of created records and company scope are decided by the server.
const ID = /^CLM-\d{3,19}$/
const EVIDENCE = /^E\d{1,3}$/

export function requestFor(action, item) {
  if (!ID.test(action.id ?? '')) throw new Error('올바르지 않은 요청 번호입니다.')
  const base = `/service-requests/${action.id}`
  const post = (path, body, result = 'item') => ({ method: 'POST', path, body, result })
  switch (action.type) {
    case 'REANALYZE': return post(`${base}/reanalysis`, undefined, 'accepted')
    case 'RESOLVE': return post(`${base}/resolution`, { note: action.note ?? '' })
    default: throw new Error('지원하지 않는 작업입니다.')
  }
}

// Original page of a manual citation. Only a request number and a citation id go into the address; the server
// decides which document page that is and whether this person may open it.
// An earlier analysis is addressed by its revision number: the same evidence id means another page in each analysis.
export function evidencePageUrl(id, evidenceId, revision) {
  if (!ID.test(id ?? '') || !EVIDENCE.test(evidenceId ?? '')) throw new Error('올바르지 않은 원본 페이지 주소입니다.')
  if (revision !== undefined && !(Number.isInteger(revision) && revision >= 1)) throw new Error('올바르지 않은 원본 페이지 주소입니다.')
  return `/api/v1/service-requests/${id}/evidence/${evidenceId}/page${revision === undefined ? '' : `?revision=${revision}`}`
}


// Customer history consists only of server-provided public system events, never comments or replies.
export function customerEvents(item) {
  return item.history.map((entry, index) => ({ id: `h${index}`, at: entry.at, who: '시스템', text: entry.text }))
    .sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0))
}
