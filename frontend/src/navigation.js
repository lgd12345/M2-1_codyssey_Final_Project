// 해시 라우트. 서버가 정적 파일만 제공하므로 새로고침·직접 링크가 그대로 동작한다.
//   공개          #/home, #/support, #/login
//   운영진        #/cases, #/cases/CLM-001 (옛 #/cases/new는 목록으로 이동)
//   고객 포털     #/portal, #/portal/CLM-001 (접근 범위는 서버의 계정 소속으로 결정)
//   부서 메일 설정 #/departments (운영진)

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
  if (path === 'departments') return { name: 'departments' }
  return { name: 'notfound' }
}

// 로그인 후 화면은 역할(보기)에 속한다. 공개 화면은 속하지 않는다.
export const VIEW_OF_ROUTE = {
  list: 'quality', new: 'quality', detail: 'quality', departments: 'quality',
  'portal-list': 'customer', 'portal-new': 'customer', 'portal-detail': 'customer',
}
export const HOME = { quality: '#/cases', customer: '#/portal' }

// 계정 역할은 둘이다. admin = 운영진(대기열·부서 메일), user = 고객(포털). 백엔드의 운영진 판정과 같아야 한다.
export const isStaff = (role) => role === 'admin'
export const homeForRole = (role) => (isStaff(role) ? HOME.quality : HOME.customer)

export function redirectFor(route, auth) {
  if (!auth) return null
  const authed = auth.authenticated === true
  const role = auth.user?.role
  const view = VIEW_OF_ROUTE[route.name]
  if (route.name === 'root') return authed ? homeForRole(role) : '#/home'
  if (!authed) return view ? '#/login' : null
  // The old operator intake URL is a redirect, never a form. Customer pages are customer-only.
  if (route.name === 'login' || route.name === 'new') return homeForRole(role)
  if (view === 'customer' && isStaff(role)) return HOME.quality
  if (view && view !== 'customer' && !isStaff(role)) return HOME.customer
  return null
}

export const caseHref = (id) => `#/cases/${id}`
export const portalHref = (id) => `#/portal/${id}`
