// 해시 라우트. 서버가 정적 파일만 제공하므로 새로고침·직접 링크가 그대로 동작한다.
//   담당자(품질)  #/cases, #/cases/new, #/cases/CLM-001
//   고객 포털     #/portal, #/portal/CLM-001
//   부서 업무함   #/work, #/work/SVC-001

const WORK_KEY = /^work\/([A-Z]{3}-\d+)$/

export function parseRoute(hash) {
  const path = (hash || '').replace(/^#\/?/, '').split('?')[0]
  if (path === '' || path === 'cases') return { name: 'list' }
  if (path === 'cases/new') return { name: 'new' }
  const detail = /^cases\/(CLM-\d+)$/.exec(path)
  if (detail) return { name: 'detail', id: detail[1] }
  if (path === 'portal') return { name: 'portal-list' }
  if (path === 'portal/new') return { name: 'portal-new' }
  const portal = /^portal\/(CLM-\d+)$/.exec(path)
  if (portal) return { name: 'portal-detail', id: portal[1] }
  if (path === 'work') return { name: 'work-list' }
  const work = WORK_KEY.exec(path)
  if (work) return { name: 'work-detail', workKey: work[1] }
  return { name: 'notfound' }
}

// 역할(보기)마다 갈 수 있는 화면 묶음. 다른 역할의 주소로 들어가면 자기 홈으로 보낸다.
export const VIEW_OF_ROUTE = {
  list: 'quality', new: 'quality', detail: 'quality',
  'portal-list': 'customer', 'portal-new': 'customer', 'portal-detail': 'customer',
  'work-list': 'dept', 'work-detail': 'dept',
}
export const HOME = { quality: '#/cases', customer: '#/portal', dept: '#/work' }

export const caseHref = (id) => `#/cases/${id}`
export const portalHref = (id) => `#/portal/${id}`
export const workHref = (workKey) => `#/work/${workKey}`
