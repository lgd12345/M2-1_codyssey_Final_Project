const PAGES = new Set(['home', 'support', 'login', 'register', 'guest', 'workspace'])

// Hash routes keep refresh/deep links compatible with the existing static server.
export function pageFromHash(hash, current = 'home') {
  if (!hash || hash === '#' || hash === '#machines') return 'home'
  if (!hash.startsWith('#/')) return current // Native anchors, including the skip link.
  const page = hash.slice(2)
  return PAGES.has(page) ? page : 'home'
}

export function needsSession(page) {
  return page === 'login' || page === 'workspace'
}

export function accountArea(user) {
  if (user?.role === 'customer') return 'customer'
  if (user?.role === 'admin' || user?.role === 'user') return 'operator'
  return 'blocked'
}
