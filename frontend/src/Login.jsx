import React, { useState } from 'react'
import { call } from './api.js'

// 이전 로그인 화면(이미지 분할)을 그대로 쓴다. 고객은 AI 결과를 직접 받지 않으므로 AI의 역할만 알린다(AI 생성 표시는 결과가 나오는 화면에 둔다).
export function Login({ onDone }) {
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
    <section className="login-experience section-container" aria-labelledby="login-title">
      <div className="login-visual"><img src="/images/cnc-machining.jpg" alt="" width="2000" height="1125" /><div><p className="eyebrow">CONNECTED TO YOUR WORK</p><h2>현장과 지원을,<br />하나로 연결합니다.</h2><a href="#/home">MORRONO MACHINE SUPPORT ↗</a></div></div>
      <form className="login" onSubmit={submit} aria-busy={busy}>
        <a className="back-link" href="#/support">← 고객센터</a>
        <h1 id="login-title">로그인</h1>
        <p className="login-description muted">발급받은 아이디 또는 가입하신 이메일로 로그인해 주세요.</p>
        <p className="ai-notice" role="note" aria-label="AI 활용 안내">
          <strong>AI 활용 안내</strong><br />
          서비스 요청은 AI가 먼저 분석하고, 서비스 담당자가 검토한 뒤 답변합니다.
        </p>
        <label>아이디 또는 이메일<input name="login_id" value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} disabled={busy} required autoFocus /></label>
        <label>비밀번호<input name="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" disabled={busy} required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="primary" disabled={busy || !loginId || !password}>{busy ? '확인 중…' : '로그인'}</button>
        <p className="login-helper muted">로그인이 어려우면 고객센터로 문의해 주세요.</p>
      </form>
    </section>
  )
}
