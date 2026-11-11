import React, { useEffect, useState } from 'react'

export function CustomerWorkspace({ auth, onLogout }) {
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setProfile(null); setError('')
    fetch('/api/v1/access/customer/profile', { credentials: 'same-origin', cache: 'no-store' })
      .then(async (response) => {
        if (response.status === 401) { if (active) onLogout(); return }
        const data = await response.json()
        if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : '회사 정보를 확인하지 못했습니다.')
        if (active) setProfile({ owner: auth.user.id, company: data.company })
      }).catch((failure) => { if (active) setError(failure.message || '연결을 확인해 주세요.') })
    return () => { active = false }
  }, [auth.user.id, onLogout, attempt])

  return <section className="customer-workspace" aria-labelledby="customer-workspace-title"><header><div><p className="eyebrow">CUSTOMER SERVICE</p><h1 id="customer-workspace-title">고객지원</h1></div></header>
    <p className="muted">{auth.user.login_id} 고객님, 환영합니다.</p>
    {error ? <div className="status-card"><p className="error" role="alert">{error}</p><button className="primary" onClick={() => setAttempt((n) => n + 1)}>다시 확인</button></div> : !profile || profile.owner !== auth.user.id ? <p role="status">회사 소속을 확인하고 있습니다…</p> : <div className="access-form-panel"><h2>{profile.company.name}</h2><p>고객 계정과 회사 소속이 확인되었습니다.</p><p className="muted">회원 전용 접수·내역 조회는 준비 중입니다. 현재 이용 가능한 문의 방법을 고객센터에서 확인해 주세요.</p><a className="site-button" href="#/support">고객센터 안내</a></div>}
  </section>
}
