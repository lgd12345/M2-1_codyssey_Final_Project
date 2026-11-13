import React, { useState } from 'react'
import { call } from './api.js'

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
    <section className="login-wrap" aria-labelledby="login-title">
      <form className="login-card" onSubmit={submit} aria-busy={busy}>
        <p className="eyebrow">MORRONO · 서비스 클레임 대응</p>
        <h1 id="login-title">로그인</h1>
        <p className="muted">허가된 담당자만 사용할 수 있습니다. 이 도구는 AI를 사용하므로 접근이 제한됩니다.</p>
        <label>아이디<input name="login_id" value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} disabled={busy} required autoFocus /></label>
        <label>비밀번호<input name="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" disabled={busy} required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="primary" disabled={busy || !loginId || !password}>{busy ? '확인 중…' : '로그인'}</button>
      </form>
    </section>
  )
}
