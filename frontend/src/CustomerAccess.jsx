import React, { useEffect, useState } from 'react'
import { AccessGuide } from './Site.jsx'

async function request(path, body, csrf) {
  const response = await fetch(`/api/v1/access${path}`, {
    method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
    headers: body ? { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const error = new Error(typeof data?.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.')
    error.status = response.status
    error.code = data?.code
    throw error
  }
  return data
}

export function Consent({ policy, value, onChange }) {
  return <div className="access-consent">
    <details><summary>개인정보 수집·이용 안내</summary><dl>
      {[['purpose', '목적'], ['items', '항목'], ['retention', '보유기간'], ['recipients', '처리·전달 대상'], ['contact', '문의·철회·삭제 요청'], ['refusal', '동의 거부권·거부 시 제한']].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{policy[key]}</dd></div>)}
      <div><dt>안내 버전</dt><dd>{policy.version}</dd></div>
    </dl></details>
    <label className="consent-check"><input type="checkbox" checked={value} onChange={(event) => onChange(event.target.checked)} />개인정보 수집·이용 안내를 확인하고 동의합니다.</label>
  </div>
}

export function CustomerAccess({ kind }) {
  const guest = kind === 'guest'
  const [capabilities, setCapabilities] = useState(null)
  const [loadError, setLoadError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [step, setStep] = useState('identity')
  const [company, setCompany] = useState('')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [verifiedEmail, setVerifiedEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [consent, setConsent] = useState(false)
  const [csrf, setCsrf] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [inquiry, setInquiry] = useState(null)

  useEffect(() => {
    let active = true
    setLoadError(false); setCapabilities(null)
    request('/status').then(async (value) => {
      if (!active) return
      setCapabilities(value)
      if (guest && value.available) {
        const session = await request('/guest/session')
        if (!active || !session.authenticated) return
        setCsrf(session.csrf_token)
        const stored = await request('/guest/inquiry')
        if (active) { setInquiry(stored.inquiry); setStep(stored.inquiry ? 'submitted' : 'inquiry') }
      }
    }).catch(() => { if (active) setLoadError(true) })
    return () => { active = false }
  }, [attempt, guest])

  useEffect(() => {
    if (!cooldown) return
    const timer = setTimeout(() => setCooldown((seconds) => Math.max(0, seconds - 1)), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  const policy = capabilities?.policy
  const available = capabilities?.available && policy && (guest || capabilities.registration_available)
  const policyBody = () => ({ policy_version: policy.version, consent })

  async function perform(action) {
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try { await action() }
    catch (failure) {
      setError(failure.message)
      if (failure.code === 'REGISTRATION_EXISTS') {
        setStep('existing'); setCode(''); setVerifiedEmail(''); setPassword(''); setConfirmation(''); setError('')
      }
      if (failure.code === 'COMPANY_NOT_FOUND' || failure.code === 'COMPANY_EMAIL_MISMATCH') {
        setStep('identity'); setCode(''); setVerifiedEmail(''); setPassword(''); setConfirmation('')
      }
      if (failure.status === 401) { setStep('identity'); setCsrf(''); setCode(''); setConsent(false) }
      if (failure.code === 'ACCESS_CONSENT_REQUIRED') {
        setStep('identity'); setConsent(false); setCode(''); setVerifiedEmail(''); setPassword(''); setConfirmation('')
        setAttempt((n) => n + 1)
      }
    } finally { setBusy(false) }
  }

  function sendCode(event) {
    event?.preventDefault()
    if (cooldown) return
    perform(async () => {
      const result = await request('/challenges', { ...policyBody(), purpose: guest ? 'guest' : 'register', company_code: company, email })
      setStep('verify'); setCode(''); setVerifiedEmail(''); setPassword(''); setConfirmation('')
      setCooldown(result.retry_after); setNotice(result.message)
    })
  }

  function verify(event) {
    event.preventDefault()
    perform(async () => {
      if (guest) {
        const session = await request('/guest/session', { ...policyBody(), code })
        setCsrf(session.csrf_token); setConsent(false); setCode(''); setStep('inquiry')
      } else {
        const result = await request('/registration/verify', { ...policyBody(), code })
        setVerifiedEmail(result.email || '')
        setStep(result.state === 'already_registered' ? 'existing' : 'account')
        if (result.state === 'already_registered') setCode('')
      }
    })
  }

  function registerAccount(event) {
    event.preventDefault()
    if (password !== confirmation) { setError('비밀번호 확인이 일치하지 않습니다.'); return }
    perform(async () => {
      await request('/registration', { ...policyBody(), code, password })
      setStep('registered'); setCode(''); setVerifiedEmail(''); setPassword(''); setConfirmation('')
    })
  }

  function submitInquiry(event) {
    event.preventDefault()
    perform(async () => {
      const result = await request('/guest/inquiry', { ...policyBody(), title, body }, csrf)
      setInquiry(result.inquiry); setStep('submitted'); setTitle(''); setBody('')
    })
  }

  const verificationActions = <>
    <button className="access-secondary" type="button" disabled={busy || cooldown > 0} onClick={sendCode}>{cooldown ? `${cooldown}초 후 인증번호 재요청` : '인증번호 재요청'}</button>
    <button className="access-secondary" type="button" disabled={busy} onClick={() => { setStep('identity'); setCode(''); setVerifiedEmail(''); setPassword(''); setConfirmation(''); setError(''); setNotice('') }}>회사·이메일 다시 입력</button>
  </>

  if (loadError) return <section className="status-card" aria-labelledby="access-load-title"><h1 id="access-load-title">서비스를 확인하지 못했습니다.</h1><p>연결을 확인한 후 다시 시도해 주세요.</p><button className="primary" onClick={() => setAttempt((n) => n + 1)}>다시 시도</button></section>
  if (!capabilities) return <section className="status-card" role="status"><h1>서비스 확인 중</h1><p>잠시만 기다려 주세요.</p></section>
  if (!available) return <AccessGuide kind={kind} />

  return <section className="customer-access section-container" aria-labelledby="customer-access-title">
    <a className="back-link" href="#/support">← 고객센터</a>
    <div className="access-heading"><p className="eyebrow">{guest ? 'GUEST SUPPORT' : 'MEMBERSHIP'}</p><h1 id="customer-access-title">{guest ? '비회원 문의' : '고객 회원가입'}</h1><p>{guest ? '회사에 등록된 이메일로 인증하고 본인의 문의를 확인하세요.' : '회사에 등록된 이메일로 인증하고 고객 계정을 만드세요.'}</p></div>
    <div className="access-form-panel">
      {step === 'registered' ? <div role="status"><span className="preparing-label">고객 회원가입 완료</span><h2>고객 계정이 만들어졌습니다.</h2><p>로그인하여 고객 서비스를 이용하세요. 운영진 매뉴얼 기능은 제공되지 않습니다.</p><a className="site-button" href="#/login">로그인 화면으로</a></div>
      : step === 'existing' ? <div role="status"><span className="preparing-label">고객 계정 확인</span><h2>이미 가입된 계정입니다.</h2><p>기존 계정으로 로그인해 서비스를 이용해 주세요.</p><a className="site-button" href="#/login">로그인 화면으로</a></div>
      : step === 'submitted' ? <div role="status"><span className="preparing-label">문의 접수 완료</span><h2>{inquiry.title}</h2><p className="inquiry-body">{inquiry.body}</p><dl className="inquiry-meta"><dt>문의번호</dt><dd>{inquiry.id}</dd><dt>접수일시</dt><dd>{new Date(inquiry.created_at).toLocaleString('ko-KR')}</dd></dl><p className="muted">이 인증 세션에서는 본인의 문의만 확인할 수 있습니다.</p></div>
      : step === 'inquiry' ? <form onSubmit={submitInquiry} aria-busy={busy}>
        <p className="access-step">문의 작성</p><label>제목<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} required disabled={busy} /></label>
        <label>문의 내용<textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} rows={7} required disabled={busy} /></label><p className="small muted">최대 4,000자 · 주민등록번호 등 불필요한 민감정보는 입력하지 마세요.</p>
        <Consent policy={policy} value={consent} onChange={setConsent} /><button className="primary" disabled={busy || !consent || !title.trim() || !body.trim()}>{busy ? '접수 중…' : '문의 접수'}</button>
      </form>
      : step === 'account' ? <form onSubmit={registerAccount} aria-busy={busy}>
        <p className="access-step">03 / 계정 정보 입력</p><p className="muted">이메일이 확인되었습니다. 로그인에 사용할 비밀번호를 설정해 주세요.</p>
        <label>로그인 이메일<input type="email" value={verifiedEmail} readOnly autoComplete="username" /></label><p className="small muted">인증한 이메일을 로그인 아이디로 사용합니다.</p>
        <label>비밀번호<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={12} maxLength={256} required disabled={busy} /></label><label>비밀번호 확인<input type="password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="new-password" minLength={12} maxLength={256} required disabled={busy} /></label><p className="small muted">비밀번호는 12~256자로 설정해 주세요. 고객 계정으로만 가입되며 운영진 권한은 부여되지 않습니다.</p>
        <button className="primary" disabled={busy || !consent || !verifiedEmail}>{busy ? '확인 중…' : '고객 계정 만들기'}</button>
        {verificationActions}
      </form>
      : step === 'verify' ? <form onSubmit={verify} aria-busy={busy}>
        <p className="access-step">02 / 이메일 인증</p><p className="muted">{email}로 받은 인증번호를 10분 안에 입력해 주세요.</p>
        <label>인증번호<input value={code} onChange={(e) => { setCode(e.target.value.replace(/[^0-9]/g, '')); setVerifiedEmail('') }} inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="[0-9]{6}" required disabled={busy} /></label>
        <button className="primary" disabled={busy || code.length !== 6 || !consent}>{busy ? '확인 중…' : '이메일 인증'}</button>
        {verificationActions}
      </form>
      : <form onSubmit={sendCode} aria-busy={busy}>
        <p className="access-step">01 / 회사 확인</p><label>회사코드<input value={company} onChange={(e) => setCompany(e.target.value.toUpperCase())} autoComplete="off" minLength={3} maxLength={24} pattern="[A-Z0-9][A-Z0-9-]{2,23}" required disabled={busy} /></label><label>회사에 등록된 이메일<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" maxLength={254} required disabled={busy} /></label>
        <Consent policy={policy} value={consent} onChange={setConsent} /><button className="primary" disabled={busy || !consent || !company.trim() || !email.trim() || cooldown > 0}>{busy ? '요청 중…' : cooldown ? `${cooldown}초 후 다시 요청` : '인증번호 받기'}</button>
      </form>}
      {notice && <p className="access-notice" role="status">{notice}</p>}{error && <p className="error" role="alert">{error}</p>}
    </div>
  </section>
}
