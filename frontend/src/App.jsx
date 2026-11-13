import React, { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { call } from './api.js'
import { Login } from './Login.jsx'
import { HOME, VIEW_OF_ROUTE, homeForRole, isStaff, parseRoute } from './navigation.js'
import { DEPT_PREFIX } from './domain/catalog.js'
import { isAnalysisRunning } from './domain/workflow.js'
import { requestFor } from './domain/actions.js'
import { HomePage, SiteFooter, SiteHeader, SupportPage } from './Site.jsx'
import { CaseList } from './pages/CaseList.jsx'
import { CaseDetail } from './pages/CaseDetail.jsx'
import { PortalList } from './pages/PortalList.jsx'
import { PortalDetail } from './pages/PortalDetail.jsx'
import { WorkList } from './pages/WorkList.jsx'
import { WorkDetail } from './pages/WorkDetail.jsx'

const TITLES = {
  home: '공작기계 고객지원', support: '고객센터', login: '로그인', list: '서비스 요청', new: '새 요청', detail: '서비스 요청',
  'portal-list': '내 서비스 요청', 'portal-new': '새 서비스 요청', 'portal-detail': '서비스 요청', 'work-list': '받은 업무', 'work-detail': '업무', notfound: '페이지를 찾을 수 없습니다',
}
const deptOfWork = key => Object.entries(DEPT_PREFIX).find(([, prefix]) => prefix === key.slice(0, 3))?.[0]
const emptyWorkspace = () => ({ owner: null, cases: [], context: null, detail: null, pending: false, error: '' })

function redirectFor(route, auth) {
  if (!auth) return null
  const authed = auth.authenticated === true
  const role = auth.user?.role
  const view = VIEW_OF_ROUTE[route.name]
  if (route.name === 'root') return authed ? homeForRole(role) : '#/home'
  if (!authed) return view ? '#/login' : null
  if (route.name === 'login') return homeForRole(role)
  if (view && view !== 'customer' && !isStaff(role)) return HOME.customer
  return null
}

export function App({ theme }) {
  const preference = useSyncExternalStore(theme.subscribe, theme.getPreference)
  const [hash, setHash] = useState(window.location.hash)
  const [auth, setAuth] = useState(null)
  const [authError, setAuthError] = useState('')
  const [workspace, setWorkspace] = useState(emptyWorkspace)
  const [refresh, setRefresh] = useState(0)
  const [deptKey, setDeptKey] = useState('service')
  const route = parseRoute(hash)
  const view = VIEW_OF_ROUTE[route.name]
  const target = redirectFor(route, auth)
  const authed = auth?.authenticated === true
  const me = auth?.user?.login_id

  useEffect(() => {
    const onHash = () => {
      const value = window.location.hash
      if (value && !value.startsWith('#/')) return
      setHash(value); window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    let active = true
    call('/auth/me').then(session => { if (active) setAuth(session) }).catch(error => { if (active) setAuthError(error.message) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!target) return
    window.history.replaceState(null, '', target); setHash(target)
  }, [target])

  useEffect(() => { document.title = `${TITLES[route.name] ?? 'MORRONO'} | MORRONO` }, [route.name])

  useEffect(() => {
    let active = true
    if (!authed || !view || target) {
      setWorkspace(emptyWorkspace())
      return () => { active = false }
    }
    const owner = auth.user.id
    setWorkspace({ ...emptyWorkspace(), owner, pending: true })
    async function load() {
      const context = await call('/service-requests/context')
      const canRead = isStaff(auth.user.role) || context.company
      const data = canRead ? await call('/service-requests') : { requests: [] }
      const detail = canRead && ['detail', 'portal-detail'].includes(route.name)
        ? await call(`/service-requests/${route.id}`) : null
      if (active) setWorkspace({ owner, context, cases: data.requests, detail, pending: false, error: '' })
    }
    load().catch(error => {
      if (active) {
        if (error.status === 401) setAuth({ authenticated: false })
        setWorkspace({ ...emptyWorkspace(), owner, error: error.message })
      }
    })
    return () => { active = false }
  }, [auth, hash, refresh])

  const createRequest = useCallback(async intake => {
    const result = await call('/service-requests', { method: 'POST', body: intake, csrf: auth?.csrf_token })
    setRefresh(value => value + 1)
    return result
  }, [auth?.csrf_token])

  const [analysisError, setAnalysisError] = useState('')
  const [analysisStarting, setAnalysisStarting] = useState(false)
  const detailId = workspace.detail?.id
  const detailRunning = isAnalysisRunning(workspace.detail)

  // Silent refresh: keeps the open tab/scroll state while the server-side analysis runs.
  const refreshDetail = useCallback(async id => {
    const [detail, data] = await Promise.all([call(`/service-requests/${id}`), call('/service-requests')])
    setWorkspace(current => current.detail?.id === id ? { ...current, detail, cases: data.requests } : current)
    return detail
  }, [])

  const startAnalysis = useCallback(async id => {
    setAnalysisError(''); setAnalysisStarting(true)
    try {
      await call(`/service-requests/${id}/analysis`, { method: 'POST', csrf: auth?.csrf_token })
      await refreshDetail(id)
    } catch (error) {
      setAnalysisError(error.message)
      await refreshDetail(id).catch(() => {})
    } finally { setAnalysisStarting(false) }
  }, [auth?.csrf_token, refreshDetail])

  useEffect(() => { setAnalysisError('') }, [route.id])

  // Screen actions go to the server one at a time, in click order: a draft saved on blur must reach the
  // server before an approval click that follows it, otherwise the approval could use an older draft.
  const [actionError, setActionError] = useState('')
  const latest = useRef(workspace)
  latest.current = workspace
  const queue = useRef(Promise.resolve())
  const refreshAll = useCallback(async id => {
    const [detail, data] = await Promise.all([
      latest.current.detail?.id === id ? call(`/service-requests/${id}`) : null, call('/service-requests')])
    setWorkspace(current => ({ ...current, cases: data.requests, detail: detail && current.detail?.id === id ? detail : current.detail }))
  }, [])
  const dispatch = useCallback(action => {
    const run = async () => {
      setActionError('')
      try {
        const current = latest.current.detail?.id === action.id ? latest.current.detail : latest.current.cases.find(c => c.id === action.id)
        const request = requestFor(action, current)
        const result = await call(request.path, { method: request.method, body: request.body, csrf: auth?.csrf_token })
        if (request.result === 'item') {
          setWorkspace(state => ({ ...state, detail: state.detail?.id === result.id ? result : state.detail,
            cases: state.cases.map(c => c.id === result.id ? result : c) }))
        } else await refreshAll(action.id)
      } catch (error) {
        if (error.status === 401) { setAuth({ authenticated: false }); return }
        setActionError(error.message)
        await refreshAll(action.id).catch(() => {}) // show what the server actually has
      }
    }
    queue.current = queue.current.then(run, run)
    return queue.current
  }, [auth?.csrf_token, refreshAll])
  useEffect(() => { setActionError('') }, [hash])

  useEffect(() => {
    if (!detailRunning || !detailId) return undefined
    const timer = setInterval(() => { refreshDetail(detailId).catch(() => {}) }, 3000)
    return () => clearInterval(timer)
  }, [detailRunning, detailId, refreshDetail])

  const signOut = useCallback(async () => {
    try { await call('/auth/logout', { method: 'POST', csrf: auth?.csrf_token }) }
    catch (error) { setAuthError(error.message); return }
    setWorkspace(emptyWorkspace())
    setAuth({ authenticated: false })
    window.location.hash = '/home'
  }, [auth])
  const workDept = route.name === 'work-detail' ? deptOfWork(route.workKey) : deptKey
  const cases = workspace.cases
  const equipment = workspace.context?.equipment ?? []
  const item = workspace.detail
  let content = null
  if (authError) content = <section className="center-card"><h1>연결을 확인해 주세요</h1><p className="error" role="alert">{authError}</p><button className="primary" onClick={() => window.location.reload()}>다시 시도</button></section>
  else if (!auth) content = <section className="center-card" role="status" aria-busy="true"><h1>로그인 상태 확인 중</h1></section>
  else if (target) content = null
  else if (route.name === 'home') content = <HomePage />
  else if (route.name === 'support') content = <SupportPage />
  else if (route.name === 'login') content = <Login onDone={session => { setAuth(session); window.location.hash = homeForRole(session.user.role).slice(1) }} />
  else if (view && (workspace.pending || workspace.owner !== auth.user.id)) content = <section className="center-card" role="status" aria-busy="true"><h1>요청을 불러오는 중</h1></section>
  else if (view && workspace.error) content = <section className="center-card"><h1>요청을 불러오지 못했습니다</h1><p className="error" role="alert">{workspace.error}</p><button onClick={() => setRefresh(value => value + 1)}>다시 시도</button></section>
  else if (route.name === 'list' || route.name === 'new') content = <CaseList cases={cases} onCreate={createRequest} equipment={equipment} modalOpen={route.name === 'new'} />
  else if (route.name === 'detail') content = <CaseDetail key={route.id} item={item} me={me} dispatch={dispatch} onAnalyze={startAnalysis} analyzing={analysisStarting} analysisError={analysisError} />
  else if (route.name === 'portal-list' || route.name === 'portal-new') content = <PortalList cases={cases} company={workspace.context?.company?.name} onCreate={createRequest} equipment={equipment} modalOpen={route.name === 'portal-new'} />
  else if (route.name === 'portal-detail') content = <PortalDetail key={route.id} item={item} dispatch={dispatch} />
  else if (route.name === 'work-list') content = <WorkList cases={cases} deptKey={deptKey} onDeptChange={setDeptKey} />
  else if (route.name === 'work-detail') content = <WorkDetail key={route.workKey} cases={cases} workKey={route.workKey} deptKey={workDept} dispatch={dispatch} />
  else content = <section className="center-card"><h1>페이지를 찾을 수 없습니다</h1><a href={authed ? homeForRole(auth.user.role) : '#/home'}>처음으로</a></section>

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">본문으로 이동</a>
      <SiteHeader preference={preference} theme={theme} session={auth} route={route} pending={!auth} onSignOut={signOut} />
      <main id="main-content" className={view && authed ? 'app-main' : 'public-main'}>
        {actionError && view && authed && <p className="notice warn" role="alert">{actionError}</p>}
        {content}
      </main>
      <SiteFooter staff={Boolean(view) && authed && isStaff(auth.user.role)} />
    </div>
  )
}
