import React, { useCallback, useEffect, useReducer, useState, useSyncExternalStore } from 'react'
import { call } from './api.js'
import { Login } from './Login.jsx'
import { HOME, VIEW_OF_ROUTE, parseRoute } from './navigation.js'
import { createInitialState, reducer } from './mock/store.js'
import { DEPARTMENTS } from './mock/data.js'
import { CUSTOMER_COMPANIES, VIEWS } from './mock/meta.js'
import { CaseList } from './pages/CaseList.jsx'
import { CaseDetail } from './pages/CaseDetail.jsx'
import { PortalList } from './pages/PortalList.jsx'
import { PortalDetail } from './pages/PortalDetail.jsx'
import { WorkList } from './pages/WorkList.jsx'
import { WorkDetail } from './pages/WorkDetail.jsx'
import { nowIso } from './ui.jsx'

const THEMES = ['light', 'dark', 'system']
const THEME_LABELS = { light: '라이트', dark: '다크', system: '시스템' }
const BRAND = { quality: '서비스 클레임', customer: '서비스 포털', dept: '업무함' }
const NAV = {
  quality: [['#/cases', '대기열']],
  customer: [['#/portal', '내 서비스 요청']],
  dept: [['#/work', '받은 업무']],
}

export function App({ theme }) {
  const preference = useSyncExternalStore(theme.subscribe, theme.getPreference)
  const [hash, setHash] = useState(window.location.hash)
  const [auth, setAuth] = useState(null) // null: 확인 중
  const [authError, setAuthError] = useState('')
  const [state, dispatch] = useReducer(reducer, undefined, createInitialState)
  const [company, setCompany] = useState(CUSTOMER_COMPANIES[0]) // 고객 포털에서 보는 고객사
  const [deptKey, setDeptKey] = useState('service') // 부서 업무함에서 보는 부서
  const route = parseRoute(hash)
  const view = VIEW_OF_ROUTE[route.name] ?? 'quality'

  useEffect(() => {
    const onHash = () => { setHash(window.location.hash); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    let active = true
    call('/auth/me').then((s) => { if (active) setAuth(s) }).catch((e) => { if (active) setAuthError(e.message) })
    return () => { active = false }
  }, [])

  // 분석 진행은 화면을 옮겨도 이어지도록 앱 수준에서 한 건씩 진행한다.
  const analyzing = state.cases.find((c) => c.status === '분석 중')
  useEffect(() => {
    if (!analyzing) return undefined
    const timer = setTimeout(() => dispatch({ type: 'ADVANCE', id: analyzing.id, at: nowIso() }), 750)
    return () => clearTimeout(timer)
  }, [analyzing?.id, analyzing?.stepsDone])

  const signOut = useCallback(async () => {
    try { await call('/auth/logout', { method: 'POST', csrf: auth?.csrf_token }) } catch { /* 이미 만료된 세션 */ }
    setAuth({ authenticated: false })
    window.location.hash = '/cases'
  }, [auth])

  const nextTheme = THEMES[(THEMES.indexOf(preference) + 1) % THEMES.length]

  if (authError) return <Shell><section className="center-card"><h1>연결을 확인해 주세요</h1><p className="error" role="alert">{authError}</p><button className="primary" onClick={() => window.location.reload()}>다시 시도</button></section></Shell>
  if (!auth) return <Shell><section className="center-card" role="status" aria-busy="true"><h1>로그인 상태 확인 중</h1></section></Shell>
  if (!auth.authenticated) return <Shell><Login onDone={setAuth} /></Shell>

  const me = auth.user.login_id
  const deptName = DEPARTMENTS.find((d) => d.key === deptKey).name
  // 보기마다 이 화면에서 일하는 사람의 이름이 달라진다(승인·처리 기록에 남는다).
  const actor = view === 'customer' ? `${company} 담당자` : view === 'dept' ? `${deptName}팀` : me

  return (
    <Shell
      header={(
        <header className="topbar">
          <a className="brand" href={HOME[view]}><span className="logo" aria-hidden="true" /><strong>MORRONO</strong><span>{BRAND[view]}</span></a>
          <nav aria-label="주 메뉴">{NAV[view].map(([href, label]) => <a key={href} href={href} aria-current="page">{label}</a>)}</nav>
          {view === 'quality' && <a className="button primary create" href="#/cases/new">새 요청</a>}
          <div className="topbar-end">
            <div className="view-switch" role="group" aria-label="시연 보기 전환">
              <span className="muted small">시연 보기</span>
              <select value={view} onChange={(e) => { window.location.hash = HOME[e.target.value].slice(1) }} aria-label="보기">
                {VIEWS.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
              </select>
              {view === 'customer' && <select value={company} onChange={(e) => setCompany(e.target.value)} aria-label="고객사">{CUSTOMER_COMPANIES.map((c) => <option key={c}>{c}</option>)}</select>}
              {view === 'dept' && <select value={deptKey} onChange={(e) => setDeptKey(e.target.value)} aria-label="부서">{DEPARTMENTS.map((d) => <option key={d.key} value={d.key}>{d.name}팀</option>)}</select>}
            </div>
            <button className="ghost" onClick={() => dispatch({ type: 'RESET' })} title="시연 데이터를 처음 상태로 되돌립니다">시연 초기화</button>
            <button className="ghost" onClick={() => theme.setPreference(nextTheme)} aria-label={`화면 테마: ${THEME_LABELS[preference]}. 변경: ${THEME_LABELS[nextTheme]}`}>테마 {THEME_LABELS[preference]}</button>
            <span className="user">{me}</span>
            <button className="ghost" onClick={signOut}>로그아웃</button>
          </div>
        </header>
      )}
    >
      {(route.name === 'list' || route.name === 'new') && <CaseList cases={state.cases} dispatch={dispatch} modalOpen={route.name === 'new'} nextId={`CLM-${String(state.nextNumber).padStart(3, '0')}`} />}
      {route.name === 'detail' && <CaseDetail key={route.id} item={state.cases.find((c) => c.id === route.id)} dispatch={dispatch} me={me} />}
      {(route.name === 'portal-list' || route.name === 'portal-new') && <PortalList cases={state.cases.filter((c) => c.intake.company === company)} company={company} dispatch={dispatch} modalOpen={route.name === 'portal-new'} nextId={`CLM-${String(state.nextNumber).padStart(3, '0')}`} />}
      {route.name === 'portal-detail' && <PortalDetail key={route.id} item={state.cases.find((c) => c.id === route.id && c.intake.company === company)} dispatch={dispatch} />}
      {route.name === 'work-list' && <WorkList cases={state.cases} deptKey={deptKey} deptName={deptName} />}
      {route.name === 'work-detail' && <WorkDetail key={route.workKey} cases={state.cases} workKey={route.workKey} deptKey={deptKey} actor={actor} dispatch={dispatch} />}
      {route.name === 'notfound' && <section className="center-card"><h1>페이지를 찾을 수 없습니다</h1><a href={HOME[view]}>처음으로</a></section>}
    </Shell>
  )
}

function Shell({ header = null, children }) {
  return (
    <div className="app">
      {header}
      <div className="demo-banner" role="note"><strong>시연용 화면</strong> 접수·분석·근거·전달은 모두 샘플 데이터이며 실제 AI, DB, 메일과 연결되어 있지 않습니다. 로그인만 실제 서버를 사용합니다.</div>
      <main id="main" className="main">{children}</main>
    </div>
  )
}
