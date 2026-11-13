// 해시 라우트: #/cases, #/cases/new, #/cases/CLM-001. 서버가 정적 파일만 제공하므로 새로고침·직접 링크가 그대로 동작한다.

export function parseRoute(hash) {
  const path = (hash || '').replace(/^#\/?/, '').split('?')[0]
  if (path === '' || path === 'cases') return { name: 'list' }
  if (path === 'cases/new') return { name: 'new' }
  const detail = /^cases\/(CLM-\d+)$/.exec(path)
  if (detail) return { name: 'detail', id: detail[1] }
  return { name: 'notfound' }
}

export const caseHref = (id) => `#/cases/${id}`
