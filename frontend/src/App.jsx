import React, { useCallback, useEffect, useReducer, useState, useSyncExternalStore } from 'react'
import { call } from './api.js'
import { Login } from './Login.jsx'
import { parseRoute } from './navigation.js'
import { createInitialState, reducer } from './mock/store.js'
import { CaseList } from './pages/CaseList.jsx'
import { CaseDetail } from './pages/CaseDetail.jsx'
import { nowIso } from './ui.jsx'

const THEMES = ['light', 'dark', 'system']
const THEME_LABELS = { light: '라이트', dark: '다크', system: '시스템' }

export function App({ theme }) {
  const preference = useSyncExternalStore(theme.subscribe, theme.getPreference)
  const [hash, setHash] = useState(window.location.hash)
  const [auth, setAuth] = useState(null) // null: 확인 중
  const [authError, setAuthError] = useState('')
  const [state, dispatch] = useReducer(reducer, undefined, createInitialState)
  const route = parseRoute(hash)

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
  return (
    <Shell
      header={(
        <header className="topbar">
          <a className="brand" href="#/cases"><span className="logo" aria-hidden="true" /><strong>MORRONO</strong><span>서비스 클레임</span></a>
          <nav aria-label="주 메뉴"><a href="#/cases" aria-current={route.name !== 'notfound' ? 'page' : undefined}>대기열</a></nav>
          <a className="button primary create" href="#/cases/new">새 요청</a>
          <div className="topbar-end">
            <button className="ghost" onClick={() => dispatch({ type: 'RESET' })} title="시연 데이터를 처음 상태로 되돌립니다">시연 초기화</button>
            <button className="ghost" onClick={() => theme.setPreference(nextTheme)} aria-label={`화면 테마: ${THEME_LABELS[preference]}. 변경: ${THEME_LABELS[nextTheme]}`}>테마 {THEME_LABELS[preference]}</button>
            <span className="user">{me}</span>
            <button className="ghost" onClick={signOut}>로그아웃</button>
          </div>
        </header>
      )}
    >
      {(route.name === 'list' || route.name === 'new') && <CaseList cases={state.cases} dispatch={dispatch} modalOpen={route.name === 'new'} nextId={`CLM-${String(state.nextNumber).padStart(3, '0')}`} />}
      {route.name === 'detail' && <CaseDetail item={state.cases.find((c) => c.id === route.id)} dispatch={dispatch} me={me} />}
      {route.name === 'notfound' && <section className="center-card"><h1>페이지를 찾을 수 없습니다</h1><a href="#/cases">대기열로</a></section>}
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
