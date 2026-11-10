import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import ReactMarkdown from 'react-markdown'
import { answerLabel, describeStep, historyText, resolveImage, toolSteps } from './chat.js'
import { documentRow, summaryLine } from './documents.js'
import { remarkPlugins } from './markdown.js'
import { SAMPLES } from './samples.js'
import { AccessGuide, HomePage, SiteFooter, SiteHeader, SupportPage } from './Site.jsx'
import { needsSession, pageFromHash } from './navigation.js'

// Temporary chat screen for checking that the manual agent works and HOW it works.
// It goes away once customer complaints are fed to the agent automatically.

const RUN_ERRORS = {
  agent_not_configured: '답변 서비스가 아직 준비되지 않았습니다. 관리자에게 문의해 주세요.',
  llm_unavailable: '답변 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.',
  invalid_agent_output: '에이전트 답변이 검증을 통과하지 못했습니다(근거 없는 인용/이미지).',
  database_unavailable: 'DB 연결에 실패했습니다.',
  interrupted: '연결이 끊겨 실행이 중단됐습니다.',
  storage_error: '결과를 저장하지 못했습니다.',
  agent_error: '답변을 처리하지 못했습니다. 문제가 계속되면 관리자에게 문의해 주세요.',
}
const API_ERRORS = {
  INVALID_CREDENTIALS: '아이디 또는 비밀번호가 올바르지 않습니다.',
  TOO_MANY_ATTEMPTS: '시도가 너무 많습니다. 10분 뒤 다시 시도하세요.',
  RUN_IN_PROGRESS: '이미 실행 중인 질문이 있습니다. 끝난 뒤 다시 시도하세요.',
  AGENT_NOT_CONFIGURED: '답변 서비스가 아직 준비되지 않았습니다. 관리자에게 문의해 주세요.',
}

class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code }
}

async function call(path, { method = 'GET', body, csrf } = {}) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (csrf && method !== 'GET') headers['X-CSRF-Token'] = csrf
  let response
  try {
    response = await fetch(`/api/v1${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined })
  } catch { throw new ApiError('서버에 연결하지 못했습니다.') }
  if (response.status === 204) return null
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.'
    throw new ApiError(API_ERRORS[data?.code] || detail, response.status, data?.code)
  }
  return data
}

export function App({ theme }) {
  const preference = useSyncExternalStore(theme.subscribe, theme.getPreference)
  const [page, setPage] = useState(() => pageFromHash(window.location.hash))
  const [auth, setAuth] = useState(null)
  const [authError, setAuthError] = useState('')
  const [sessionAttempt, setSessionAttempt] = useState(0)
  const firstPage = useRef(true)
  const sessionPage = needsSession(page)
  const onLogout = useCallback(() => { setAuth({ authenticated: false }); window.location.hash = '/login' }, [])

  useEffect(() => {
    const changePage = () => setPage((current) => pageFromHash(window.location.hash, current))
    window.addEventListener('hashchange', changePage)
    return () => window.removeEventListener('hashchange', changePage)
  }, [])

  useEffect(() => {
    document.title = `${page === 'home' ? '공작기계 고객지원' : page === 'support' ? '고객센터' : sessionPage ? '로그인 · 매뉴얼 지원' : '서비스 이용 안내'} | MORRONO`
    if (window.location.hash === '#machines') document.getElementById('machines')?.scrollIntoView()
    else if (!firstPage.current) {
      window.scrollTo(0, 0)
      document.getElementById('main-content')?.focus({ preventScroll: true })
    }
    firstPage.current = false
  }, [page, sessionPage])

  useEffect(() => {
    if (!sessionPage) return
    let active = true
    setAuth(null)
    setAuthError('')
    call('/auth/me').then((session) => { if (active) setAuth(session) })
      .catch((error) => { if (active) setAuthError(error.message) })
    return () => { active = false }
  }, [sessionAttempt, sessionPage])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">본문으로 이동</a>
      <SiteHeader preference={preference} theme={theme} authenticated={auth?.authenticated} page={page} />
      <main id="main-content" className={`app-main ${sessionPage ? 'session-main' : 'public-main'}`} tabIndex={-1}>
        {!sessionPage ? (
          page === 'support' ? <SupportPage /> : page === 'register' || page === 'guest' ? <AccessGuide kind={page} /> : <HomePage />
        ) : authError ? (
          <section className="status-card" aria-labelledby="session-error-title">
            <h1 id="session-error-title">연결을 확인해 주세요</h1>
            <p className="error" role="alert">{authError}</p>
            <p className="muted">로그인 상태를 확인하지 못했습니다. 연결 후 다시 시도해 주세요.</p>
            <button className="primary" onClick={() => setSessionAttempt((attempt) => attempt + 1)}>다시 시도</button>
          </section>
        ) : !auth ? (
          <section className="status-card" aria-busy="true" role="status">
            <h1>로그인 상태 확인 중</h1>
            <p className="muted">잠시만 기다려 주세요.</p>
          </section>
        ) : auth.authenticated ? <Chat auth={auth} onLogout={onLogout} /> : <Login onDone={(session) => { setAuth(session); window.location.hash = '/workspace' }} />}
      </main>
      <SiteFooter />
    </div>
  )
}

function Login({ onDone }) {
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event) {
    event.preventDefault()
    setBusy(true); setError('')
    try { onDone(await call('/auth/login', { method: 'POST', body: { login_id: loginId, password } })) }
    catch (e) { setError(e.message); setPassword('') }
    finally { setBusy(false) }
  }
  return (
    <section className="login-experience" aria-labelledby="login-title">
      <div className="login-visual"><img src="/images/cnc-machining.jpg" alt="" width="2000" height="1125" /><div><p className="eyebrow">CONNECTED TO YOUR WORK</p><h2>현장과 지원을,<br />하나로 연결합니다.</h2><a href="#/home">MORRONO MACHINE SUPPORT ↗</a></div></div>
      <form className="login" onSubmit={submit} aria-busy={busy}>
        <a className="back-link" href="#/support">← 고객센터</a>
        <h1 id="login-title">로그인</h1>
        <p className="login-description muted">등록된 계정으로 매뉴얼과 답변을 확인하세요.</p>
        <p className="ai-notice" role="note" aria-label="AI 생성 콘텐츠 안내">
          <strong>AI 생성 콘텐츠 안내</strong><br />
          로그인 후 제공되는 답변은 AI가 생성합니다. 내용이 부정확할 수 있으니 인용된 근거와 원본 매뉴얼을 함께 확인해 주세요.
        </p>
        <label>아이디<input name="login_id" value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} disabled={busy} required autoFocus /></label>
        <label>비밀번호<input name="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" disabled={busy} required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy || !loginId || !password}>{busy ? '확인 중…' : '로그인'}</button>
        <p className="login-helper muted">계정 이용이 어려우면 관리자에게 문의해 주세요.</p>
        <div className="login-extra"><a href="#/register">회원가입 안내</a><a href="#/guest">비회원 문의 안내</a></div>
      </form>
    </section>
  )
}

function Chat({ auth, onLogout }) {
  const csrf = auth.csrf_token
  const runId = useRef(null)
  const [input, setInput] = useState('')
  const [finished, setFinished] = useState({}) // assistant message id -> { steps, run }

  const transport = useMemo(() => new DefaultChatTransport({
    api: '/api/v1/agent/stream',
    credentials: 'same-origin',
    headers: () => ({ 'X-CSRF-Token': csrf }),
    fetch: async (url, init) => {
      const response = await fetch(url, init)
      if (response.status === 401) onLogout()
      if (!response.ok) {
        // Show the server's Korean message instead of the raw response body.
        const data = await response.json().catch(() => null)
        throw new Error(API_ERRORS[data?.code] || data?.detail || '요청을 처리하지 못했습니다.')
      }
      runId.current = response.headers.get('X-Run-Id')
      return response
    },
  }), [csrf, onLogout])

  const { messages, sendMessage, status, error, setMessages } = useChat({ transport })
  const busy = status === 'submitted' || status === 'streaming'
  const latest = useRef(messages)
  latest.current = messages
  const previous = useRef(status)

  // When a stream ends, replace its unvalidated output with the server's validated result.
  useEffect(() => {
    const wasBusy = previous.current === 'submitted' || previous.current === 'streaming'
    previous.current = status
    if (!wasBusy || busy) return
    const assistant = [...latest.current].reverse().find((m) => m.role === 'assistant')
    const id = runId.current
    runId.current = null
    if (!assistant || !id) return
    const steps = toolSteps(assistant.parts)
    call(`/agent/runs/${id}`).catch(() => null).then((run) => {
      setFinished((current) => ({ ...current, [assistant.id]: { steps, run } }))
      // Next turn's history is plain text only: no tool parts, nothing the server has not validated.
      setMessages((current) => current.map((m) => m.id === assistant.id
        ? { ...m, parts: [{ type: 'text', text: historyText(run) }] } : m))
    })
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps

  function send(text) {
    const question = text.trim()
    if (!question || busy) return
    setInput('')
    sendMessage({ text: question })
  }
  function reset() { setMessages([]); setFinished({}) }
  async function logout() {
    try { await call('/auth/logout', { method: 'POST', csrf }) } finally { onLogout() }
  }

  return (
    <div className="wrap">
      <header><h1>매뉴얼 질의</h1>
        <div className="chat-actions"><span className="muted">{auth.user.login_id}</span>
          <button className="link" onClick={reset} disabled={busy}>새 대화</button>
          <button className="link" onClick={logout}>로그아웃</button></div></header>
      <p className="notice">매뉴얼 질의 확인용 화면입니다. 대화는 새로고침하면 사라지고, 실행 기록은 서버에 저장됩니다.</p>

      <Documents />

      <div className="thread" role="log" aria-label="질문과 답변">
        {messages.length === 0 && <div className="empty-state"><h2>어떤 내용을 찾으시나요?</h2><p className="muted">질문을 입력하거나 아래 예시를 선택해 보세요.</p></div>}
        {messages.map((message, index) => message.role === 'user'
          ? <div key={message.id} className="bubble user">{textOf(message)}</div>
          : <Assistant key={message.id} message={message} info={finished[message.id]}
              live={busy && index === messages.length - 1} />)}
        {status === 'submitted' && <div className="bubble bot muted" role="status">매뉴얼을 확인하고 있습니다…</div>}
        {error && <p className="error" role="alert">{error.message}</p>}
      </div>

      <div className="samples">{SAMPLES.map((s) => (
        <button key={s.question} className="chip" onClick={() => send(s.question)} disabled={busy} title={s.question}>
          <b>{s.label}</b> {s.question}</button>))}</div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input) }} aria-busy={busy}>
        <div className="composer-field">
        <label htmlFor="manual-question">매뉴얼 질문</label>
        <textarea id="manual-question" name="question" rows={2} value={input} maxLength={4000} placeholder="확인할 기종·알람·증상을 입력하세요"
          aria-describedby="question-help"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.nativeEvent.keyCode !== 229) { e.preventDefault(); send(input) } }} />
        <span id="question-help" className="muted small">Enter로 전송 · Shift+Enter로 줄바꿈 · 최대 4,000자</span>
        </div>
        <button className="primary" disabled={busy || !input.trim()}>{busy ? '실행 중…' : '전송'}</button>
      </form>
    </div>
  )
}

function Documents() {
  const [overview, setOverview] = useState(null)
  const [failure, setFailure] = useState('')
  useEffect(() => {
    let active = true
    call('/documents').then((result) => { if (active) setOverview(result) })
      .catch((error) => { if (active) setFailure(error.status === 403 ? '문서 목록을 볼 권한이 없습니다.' : '문서 목록을 불러오지 못했습니다.') })
    return () => { active = false }
  }, [])
  return (
    <details className="docs">
      <summary>{failure || summaryLine(overview)}</summary>
      {failure && <p className="error" role="alert">{failure}</p>}
      {overview?.documents.length === 0 && <p className="muted">등록된 매뉴얼이 없습니다.</p>}
      {overview && overview.documents.length > 0 && (
        <div className="table-scroll" role="region" aria-label="등록된 매뉴얼 목록" tabIndex={0}>
        <table>
          <caption className="sr-only">매뉴얼별 검색·벡터 색인 현황</caption>
          <thead><tr><th>문서</th><th>기종</th><th>전체</th><th>검색 대상</th><th>벡터</th></tr></thead>
          <tbody>{overview.documents.map(documentRow).map((row) => (
            <tr key={row.key}><td>{row.title}</td><td>{row.machines}</td>
              <td>{row.pages}</td><td>{row.searchable}</td><td>{row.vector}</td></tr>))}</tbody>
        </table></div>)}
      <p className="muted small">검색 대상은 본문이 있는 페이지입니다(표지·목차·번호만 있는 도면 쪽은 제외). 벡터는 임베딩이 만들어진 페이지 수입니다.</p>
    </details>
  )
}

const textOf = (message) => message.parts.filter((p) => p.type === 'text').map((p) => p.text).join('')

function Assistant({ message, info, live }) {
  const steps = info ? info.steps : toolSteps(message.parts)
  const run = info?.run
  return (
    <div className="bubble bot" aria-label="에이전트 응답">
      {steps.length > 0 && <Steps steps={steps} />}
      {live && !info && <p className="muted">에이전트가 작업 중입니다…</p>}
      {info && !run && <p className="error" role="alert">검증된 결과를 불러오지 못했습니다.</p>}
      {run?.status === 'failed' && <p className="error" role="alert">{RUN_ERRORS[run.error_code] || '답변을 처리하지 못했습니다.'}</p>}
      {run?.answer_markdown && <Answer run={run} />}
    </div>
  )
}

function Steps({ steps }) {
  return (
    <details className="steps" open>
      <summary>에이전트 동작 ({steps.length}회 도구 호출)</summary>
      <ol>{steps.map((step) => {
        const view = describeStep(step)
        return (
          <li key={step.id} className={view.status}>
            <code>{view.title}</code> {view.detail}
            {view.status === 'running' && <span className="muted"> … 실행 중</span>}
            {view.result && <span> → {view.result}</span>}
          </li>)
      })}</ol>
    </details>
  )
}

const markdownComponents = (assets) => ({
  // Only pages the run opened can be images; links are limited to http(s). Raw HTML is never rendered.
  img: ({ src, alt }) => {
    const image = resolveImage(src, assets)
    return image
      ? <span className="source-figure"><img src={image.url} alt={alt || `원본 PDF ${image.page}쪽`} /><span className="source-caption">원본 PDF {image.page}쪽</span></span>
      : <span className="muted">[이미지 생략]</span>
  },
  table: ({ children }) => <div className="table-scroll" role="region" aria-label="답변 표" tabIndex={0}><table>{children}</table></div>,
  pre: ({ children }) => <pre tabIndex={0}>{children}</pre>,
  a: ({ href, children }) => (/^https?:\/\//i.test(href || '')
    ? <a href={href} target="_blank" rel="noreferrer noopener">{children}</a> : <span>{children}</span>),
})

function Answer({ run }) {
  const referenced = new Set([...run.answer_markdown.matchAll(/asset:([A-Za-z0-9_-]+)/g)].map((m) => m[1]))
  const others = (run.assets || []).filter((a) => !referenced.has(a.asset_id))
  return (
    <div className="answer">
      <p className="ai-notice">AI가 생성한 답변입니다. 인용된 근거와 원본 매뉴얼을 함께 확인해 주세요.</p>
      <span className={`tag ${run.answer_status}`}>{answerLabel(run.answer_status)}</span>
      <ReactMarkdown remarkPlugins={remarkPlugins} urlTransform={(url) => url} components={markdownComponents(run.assets)}>
        {run.answer_markdown}
      </ReactMarkdown>
      {run.citations?.length > 0 && (
        <div className="source-label"><strong>답변에 인용된 매뉴얼</strong><ul className="citations">{run.citations.map((c, i) =>
          <li key={i}>{c.title} · PDF {c.page}쪽{c.printed_page ? ` (인쇄 ${c.printed_page})` : ''}</li>)}</ul></div>)}
      {run.case_citations?.length > 0 && (
        <div className="source-label"><strong>답변에 인용된 과거 서비스 사례</strong><ul className="citations">{run.case_citations.map((c) =>
          <li key={c.fsr_no}>{c.fsr_no}{c.machine ? ` · ${c.machine}` : ''}{c.registered_on ? ` · ${c.registered_on}` : ''}</li>)}</ul></div>)}
      {others.length > 0 && (
        <details><summary>에이전트가 연 원본 페이지 ({others.length})</summary>
          <div className="gallery">{others.map((a) =>
            <figure key={a.asset_id}><img src={a.url} alt={`원본 PDF ${a.pdf_page}쪽`} /><figcaption>PDF {a.pdf_page}쪽</figcaption></figure>)}</div></details>)}
    </div>
  )
}
