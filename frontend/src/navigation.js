// 해시 라우트. 서버가 정적 파일만 제공하므로 새로고침·직접 링크가 그대로 동작한다.
//   공개          #/home, #/support, #/login
//   담당자(품질)  #/cases, #/cases/new, #/cases/CLM-001
//   고객 포털     #/portal, #/portal/CLM-001 (접근 범위는 서버의 계정 소속으로 결정)
//   부서 업무함   #/work, #/work/SVC-001

const WORK_KEY = /^work\/([A-Z]{3}-\d+)$/
const PUBLIC = { home: 'home', support: 'support', login: 'login' }

export function parseRoute(hash) {
  const path = (hash || '').replace(/^#\/?/, '').split('?')[0]
  if (path === '') return { name: 'root' }
  if (PUBLIC[path]) return { name: PUBLIC[path] }
  if (path === 'cases') return { name: 'list' }
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

// 로그인 후 화면은 역할(보기)에 속한다. 공개 화면은 속하지 않는다.
export const VIEW_OF_ROUTE = {
  list: 'quality', new: 'quality', detail: 'quality',
  'portal-list': 'customer', 'portal-new': 'customer', 'portal-detail': 'customer',
  'work-list': 'dept', 'work-detail': 'dept',
}
export const HOME = { quality: '#/cases', customer: '#/portal', dept: '#/work' }

// 계정 역할은 둘이다. admin = 운영진(담당자 대기열·받은 업무), user = 고객(포털). 백엔드의 운영진 판정과 같아야 한다.
export const isStaff = (role) => role === 'admin'
export const homeForRole = (role) => (isStaff(role) ? HOME.quality : HOME.customer)

export const caseHref = (id) => `#/cases/${id}`
export const portalHref = (id) => `#/portal/${id}`
export const workHref = (workKey) => `#/work/${workKey}`
