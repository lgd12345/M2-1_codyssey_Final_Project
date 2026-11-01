import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import ReactMarkdown from 'react-markdown'
import { answerLabel, describeStep, historyText, resolveImage, toolSteps } from './chat.js'
import { documentRow, summaryLine } from './documents.js'
import { remarkPlugins } from './markdown.js'
import { SAMPLES } from './samples.js'

// Temporary chat screen for checking that the manual agent works and HOW it works.
// It goes away once customer complaints are fed to the agent automatically.

const RUN_ERRORS = {
  agent_not_configured: 'LLM 설정(.env)이 비어 있습니다.',
  llm_unavailable: 'LLM 프록시 호출에 실패했습니다.',
  invalid_agent_output: '에이전트 답변이 검증을 통과하지 못했습니다(근거 없는 인용/이미지).',
  database_unavailable: 'DB 연결에 실패했습니다.',
  interrupted: '연결이 끊겨 실행이 중단됐습니다.',
  storage_error: '결과를 저장하지 못했습니다.',
  agent_error: '알 수 없는 오류입니다(서버 로그 확인).',
}
const API_ERRORS = {
  INVALID_CREDENTIALS: '아이디 또는 비밀번호가 올바르지 않습니다.',
  TOO_MANY_ATTEMPTS: '시도가 너무 많습니다. 10분 뒤 다시 시도하세요.',
  RUN_IN_PROGRESS: '이미 실행 중인 질문이 있습니다. 끝난 뒤 다시 시도하세요.',
  AGENT_NOT_CONFIGURED: 'LLM 설정(.env)이 비어 있습니다.',
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

export function App() {
  const [auth, setAuth] = useState(null)
  useEffect(() => { call('/auth/me').then(setAuth).catch(() => setAuth({ authenticated: false })) }, [])
  if (!auth) return <p className="muted pad">불러오는 중…</p>
  if (!auth.authenticated) return <Login onDone={setAuth} />
  return <Chat auth={auth} onLogout={() => setAuth({ authenticated: false })} />
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
    <form className="login" onSubmit={submit}>
      <h1>매뉴얼 에이전트 테스트</h1>
      <label>아이디<input value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" autoFocus /></label>
      <label>비밀번호<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={busy || !loginId || !password}>{busy ? '확인 중…' : '로그인'}</button>
    </form>
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
      <header><strong>매뉴얼 에이전트 테스트</strong>
        <span className="muted">{auth.user.login_id}
          <button className="link" onClick={reset} disabled={busy}>새 대화</button>
          <button className="link" onClick={logout}>로그아웃</button></span></header>
      <p className="notice">임시 확인용 화면입니다. 고객 민원이 에이전트로 자동 전달되는 구조가 되면 제거됩니다. 대화는 새로고침하면 사라지고, 실행 기록은 서버에 저장됩니다.</p>

      <Documents />

      <div className="thread">
        {messages.length === 0 && <p className="muted">질문을 입력하거나 예시를 눌러 보세요.</p>}
        {messages.map((message, index) => message.role === 'user'
          ? <div key={message.id} className="bubble user">{textOf(message)}</div>
          : <Assistant key={message.id} message={message} info={finished[message.id]}
              live={busy && index === messages.length - 1} />)}
        {status === 'submitted' && <div className="bubble bot muted">조사 중…</div>}
        {error && <p className="error" role="alert">{error.message}</p>}
      </div>

      <div className="samples">{SAMPLES.map((s) => (
        <button key={s.question} className="chip" onClick={() => send(s.question)} disabled={busy} title={s.question}>
          <b>{s.label}</b> {s.question}</button>))}</div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input) }}>
        <textarea rows={2} value={input} maxLength={4000} placeholder="매뉴얼에 대해 질문하세요 (Enter 전송, Shift+Enter 줄바꿈)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(input) } }} />
        <button className="primary" disabled={busy || !input.trim()}>{busy ? '실행 중…' : '전송'}</button>
      </form>
    </div>
  )
}

function Documents() {
  const [overview, setOverview] = useState(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => { call('/documents').then(setOverview).catch(() => setFailed(true)) }, [])
  return (
    <details className="docs">
      <summary>{failed ? '문서 목록을 불러오지 못했습니다.' : summaryLine(overview)}</summary>
      {overview && (
        <table>
          <thead><tr><th>문서</th><th>기종</th><th>전체</th><th>검색 대상</th><th>벡터</th></tr></thead>
          <tbody>{overview.documents.map(documentRow).map((row) => (
            <tr key={row.key}><td>{row.title}</td><td>{row.machines}</td>
              <td>{row.pages}</td><td>{row.searchable}</td><td>{row.vector}</td></tr>))}</tbody>
        </table>)}
      <p className="muted small">검색 대상은 본문이 있는 페이지입니다(표지·목차·번호만 있는 도면 쪽은 제외). 벡터는 임베딩이 만들어진 페이지 수입니다.</p>
    </details>
  )
}

const textOf = (message) => message.parts.filter((p) => p.type === 'text').map((p) => p.text).join('')

function Assistant({ message, info, live }) {
  const steps = info ? info.steps : toolSteps(message.parts)
  const run = info?.run
  return (
    <div className="bubble bot">
      {steps.length > 0 && <Steps steps={steps} />}
      {live && !info && <p className="muted">에이전트가 작업 중입니다…</p>}
      {info && !run && <p className="error">검증된 결과를 불러오지 못했습니다.</p>}
      {run?.status === 'failed' && <p className="error">{RUN_ERRORS[run.error_code] || run.error_code}</p>}
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
      ? <figure><img src={image.url} alt={alt || `원본 PDF ${image.page}쪽`} /><figcaption>원본 PDF {image.page}쪽</figcaption></figure>
      : <span className="muted">[이미지 생략]</span>
  },
  a: ({ href, children }) => (/^https?:\/\//i.test(href || '')
    ? <a href={href} target="_blank" rel="noreferrer noopener">{children}</a> : <span>{children}</span>),
})

function Answer({ run }) {
  const referenced = new Set([...run.answer_markdown.matchAll(/asset:([A-Za-z0-9_-]+)/g)].map((m) => m[1]))
  const others = (run.assets || []).filter((a) => !referenced.has(a.asset_id))
  return (
    <div className="answer">
      <span className={`tag ${run.answer_status}`}>{answerLabel(run.answer_status)}</span>
      <ReactMarkdown remarkPlugins={remarkPlugins} urlTransform={(url) => url} components={markdownComponents(run.assets)}>
        {run.answer_markdown}
      </ReactMarkdown>
      {run.citations?.length > 0 && (
        <ul className="citations">{run.citations.map((c, i) =>
          <li key={i}>{c.title} · PDF {c.page}쪽{c.printed_page ? ` (인쇄 ${c.printed_page})` : ''}</li>)}</ul>)}
      {others.length > 0 && (
        <details><summary>에이전트가 연 원본 페이지 ({others.length})</summary>
          <div className="gallery">{others.map((a) =>
            <figure key={a.asset_id}><img src={a.url} alt={`원본 PDF ${a.pdf_page}쪽`} /><figcaption>PDF {a.pdf_page}쪽</figcaption></figure>)}</div></details>)}
    </div>
  )
}
