import React, { useEffect, useState } from 'react'

async function request(path, auth, method = 'GET', body) {
  const response = await fetch(`/api/v1/companies${path}`, { method, credentials: 'same-origin', cache: 'no-store',
    headers: body ? { 'Content-Type': 'application/json', 'X-CSRF-Token': auth.csrf_token } : {},
    body: body ? JSON.stringify(body) : undefined })
  const value = await response.json().catch(() => null)
  if (!response.ok) { const error = new Error(value?.detail || '연결을 확인한 뒤 다시 시도해 주세요.'); error.status = response.status; throw error }
  return value
}

function Pager({ page, total, onChange, busy }) {
  const last = Math.max(1, Math.ceil(total / 20))
  return <nav className="registry-pager" aria-label="목록 페이지"><span>총 {total.toLocaleString()}건 · {page} / {last}</span><button disabled={busy || page <= 1} onClick={() => onChange(page - 1)}>이전</button><button disabled={busy || page >= last} onClick={() => onChange(page + 1)}>다음</button></nav>
}

function EquipmentForm({ editing, busy, onSave, onCancel }) {
  const [model, setModel] = useState(editing?.model_name || '')
  const [serial, setSerial] = useState(editing?.serial_number || '')
  const [site, setSite] = useState(editing?.manufacturing_site || '')
  const [quantity, setQuantity] = useState(1)
  const [confirmed, setConfirmed] = useState(editing?.is_confirmed || false)
  const [active, setActive] = useState(editing?.is_active ?? true)
  const [requestId] = useState(() => crypto.randomUUID())
  return <form className="registry-form" onSubmit={(event) => {
    event.preventDefault()
    const body = { model_name: model, serial_number: serial || null, manufacturing_site: site || null, is_confirmed: confirmed }
    onSave(editing ? { ...body, is_active: active, expected_version: editing.version } : { ...body, quantity: Number(quantity), request_id: requestId })
  }}>
    <div className="registry-section-heading"><h3>{editing ? '설비 수정' : '설비 등록'}</h3>{editing && <button type="button" className="registry-text-button" disabled={busy} onClick={onCancel}>취소</button>}</div>
    <div className="registry-form-grid"><label>기종명<input value={model} onChange={(e) => setModel(e.target.value)} maxLength={120} required disabled={busy} /></label><label>호기<input value={serial} onChange={(e) => { setSerial(e.target.value); if (e.target.value) setQuantity(1) }} maxLength={120} disabled={busy} placeholder="모르면 비워 두세요" /></label><label>제조처<input value={site} onChange={(e) => setSite(e.target.value)} maxLength={120} disabled={busy} /></label>{!editing && <label>등록 대수<input type="number" min={1} max={100} value={quantity} onChange={(e) => setQuantity(e.target.value)} disabled={busy || Boolean(serial)} required /></label>}</div>
    <label className="registry-checkbox"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={busy} />실제 보유 회사와 설비 정보를 확인했습니다.</label>
    {editing && <label className="registry-checkbox"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} disabled={busy} />활성 설비</label>}
    <p className="registry-help">호기가 있으면 한 대씩 등록합니다. 호기가 없는 설비는 대수만큼 등록되며, 확인 전 자료는 보유 확인 대수에 포함되지 않습니다.</p>
    <button className="primary" disabled={busy || !model.trim()}>{busy ? '저장 중…' : editing ? '설비 저장' : '설비 등록'}</button>
  </form>
}

const eventLabels = { 'company.created': '고객사 등록', 'company.imported': '고객사 자료 등록', 'company.updated': '회사 정보 변경', 'contact.created': '이메일 등록', 'contact.updated': '이메일 상태 변경', 'equipment.created': '설비 등록', 'equipment.imported': '설비 자료 등록', 'equipment.updated': '설비 정보 변경' }

export function CompanyRegistry({ auth, onLogout }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [list, setList] = useState(null)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [equipmentPage, setEquipmentPage] = useState(1)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [newCode, setNewCode] = useState('')
  const [newName, setNewName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [companyActive, setCompanyActive] = useState(true)
  const [email, setEmail] = useState('')
  const [emailConfirmed, setEmailConfirmed] = useState(false)
  const [formGeneration, setFormGeneration] = useState(0)

  function failure(error) { if (error.status === 401) onLogout(); else setError(error.message) }
  useEffect(() => {
    let active = true
    request('/status', auth).then((v) => { if (active) setStatus(v) }).catch((e) => { if (active) failure(e) })
    return () => { active = false }
  }, [auth, onLogout, refresh])
  useEffect(() => {
    if (!status?.available) return
    let active = true
    setList(null)
    request(`?search=${encodeURIComponent(search)}&page=${page}`, auth).then((v) => { if (active) setList(v) }).catch((e) => { if (active) failure(e) })
    return () => { active = false }
  }, [status?.available, search, page, refresh, auth, onLogout])
  useEffect(() => {
    if (!selected || !status?.available) return
    let active = true
    setDetail(null); setEditing(null)
    request(`/${selected}?page=${equipmentPage}`, auth).then((v) => {
      if (active) { setDetail(v); setCompanyName(v.company.name); setCompanyActive(v.company.is_active) }
    }).catch((e) => { if (active) failure(e) })
    return () => { active = false }
  }, [selected, equipmentPage, refresh, status?.available, auth, onLogout])

  async function perform(action, message) {
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try { await action(); setNotice(message); setRefresh((n) => n + 1) }
    catch (e) { failure(e) }
    finally { setBusy(false) }
  }
  function choose(identity) { setSelected(identity); setEquipmentPage(1); setEmail(''); setEmailConfirmed(false); setEditing(null); setError(''); setNotice('') }

  const company = detail?.company.id === selected ? detail.company : null
  return <section className="registry-page" aria-labelledby="registry-title">
    <header className="registry-heading"><div><p className="eyebrow">CUSTOMER OPERATIONS</p><h1 id="registry-title">고객사 관리</h1><p className="muted">회사와 등록 이메일, 현장의 설비를 한곳에서 관리합니다.</p></div><a className="registry-back" href="#/workspace">매뉴얼로 돌아가기 ↗</a></header>
    {status?.demo && <p className="registry-demo" role="note">시연 명부입니다. 생성된 이메일은 발송·가입에 사용되지 않으며 실제 연락처를 별도로 등록해야 합니다.</p>}
    {error && <div className="registry-message"><p className="error" role="alert">{error}</p><button onClick={() => { setError(''); setRefresh((n) => n + 1) }} disabled={busy}>최신 정보 불러오기</button></div>}
    {notice && <p className="registry-notice" role="status">{notice}</p>}
    {!status ? <p role="status">관리 서비스를 확인하고 있습니다…</p> : !status.available ? <div className="registry-panel"><h2>고객사 관리를 준비하고 있습니다.</h2><p className="muted">관리 데이터 연결이 완료되면 사용할 수 있습니다.</p></div> : <>
      <div className="registry-toolbar"><form onSubmit={(e) => { e.preventDefault(); setSearch(query); setPage(1); choose(null) }}><label className="sr-only" htmlFor="registry-search">회사명 또는 회사코드 검색</label><input id="registry-search" type="search" value={query} maxLength={120} onChange={(e) => setQuery(e.target.value)} placeholder="회사명 또는 회사코드 검색" disabled={busy} /><button disabled={busy}>검색</button></form><button className="primary" disabled={busy} onClick={() => setShowNew(!showNew)}>{showNew ? '등록 닫기' : '고객사 등록'}</button></div>
      {showNew && <form className="registry-panel registry-form" onSubmit={(e) => { e.preventDefault(); perform(async () => {
        const value = await request('', auth, 'POST', { code: newCode, name: newName }); setShowNew(false); setNewCode(''); setNewName(''); choose(value.id)
      }, '고객사를 등록했습니다.') }}><h2>새 고객사</h2><div className="registry-form-grid"><label>회사명<input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={120} required disabled={busy} /></label><label>회사코드<input value={newCode} onChange={(e) => setNewCode(e.target.value.toUpperCase())} pattern="[A-Z0-9][A-Z0-9-]{2,23}" maxLength={24} minLength={3} required disabled={busy} /></label></div><p className="registry-help">회사코드는 등록 후 유지됩니다. 3~24자의 영문·숫자·하이픈을 사용하세요.</p><button className="primary" disabled={busy}>고객사 저장</button></form>}
      {selected ? !company ? <p role="status">고객사 정보를 불러오고 있습니다…</p> : <>
        <button className="registry-text-button" disabled={busy} onClick={() => choose(null)}>← 고객사 목록</button>
        <div className="registry-company-title"><div><span className="registry-code">{company.code}</span><h2>{company.name}</h2></div><span className={`registry-badge ${company.is_active ? '' : 'muted'}`}>{company.is_active ? '활성 회사' : '비활성 회사'}</span></div>
        <div className="registry-stats"><div><span>등록 설비</span><strong>{detail.equipment_summary.total.toLocaleString()}<small>대</small></strong></div><div><span>보유 확인</span><strong>{detail.equipment_summary.confirmed.toLocaleString()}<small>대</small></strong></div><div><span>활성 이메일</span><strong>{detail.contacts.filter((c) => c.is_active).length}<small>개</small></strong></div></div>
        <div className="registry-columns"><div className="registry-panel"><h3>회사 정보</h3><form className="registry-form" onSubmit={(e) => { e.preventDefault(); perform(() => request(`/${selected}`, auth, 'PUT', { name: companyName, is_active: companyActive, expected_version: company.version }), '회사 정보를 저장했습니다.') }}><label>고객사명<input value={companyName} onChange={(e) => setCompanyName(e.target.value)} maxLength={120} required disabled={busy} /></label><label className="registry-checkbox"><input type="checkbox" checked={companyActive} onChange={(e) => setCompanyActive(e.target.checked)} disabled={busy} />활성 회사</label><p className="registry-help">비활성 회사는 신규 가입·비회원 인증을 이용할 수 없습니다. 기존 계정의 이용 중지는 계정 관리에서 처리합니다.</p><button disabled={busy}>회사 정보 저장</button></form></div>
          <div className="registry-panel"><h3>등록 이메일</h3><ul className="registry-contacts">{detail.contacts.map((c) => <li key={c.id}><div><span className="registry-email">{c.email}</span><small>{c.is_placeholder ? '시연용 · 가입 불가' : c.is_active ? '사용 중' : '비활성'}</small></div>{!c.is_placeholder && <button disabled={busy} aria-label={`${c.email} ${c.is_active ? '사용 중지' : '활성화'}`} onClick={() => perform(() => request(`/${selected}/contacts/${c.id}`, auth, 'PUT', { is_active: !c.is_active, expected_version: c.version }), '이메일 상태를 변경했습니다.')}>{c.is_active ? '사용 중지' : '활성화'}</button>}</li>)}</ul>{!detail.contacts.length && <p className="muted">등록된 이메일이 없습니다.</p>}<form className="registry-form registry-contact-form" onSubmit={(e) => { e.preventDefault(); perform(async () => { await request(`/${selected}/contacts`, auth, 'POST', { email, confirmed: emailConfirmed }); setEmail(''); setEmailConfirmed(false) }, '등록 이메일을 추가했습니다.') }}><label>새 등록 이메일<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} required disabled={busy} /></label><label className="registry-checkbox"><input type="checkbox" checked={emailConfirmed} onChange={(e) => setEmailConfirmed(e.target.checked)} disabled={busy} />해당 회사의 담당 이메일임을 확인했습니다.</label><button disabled={busy || !emailConfirmed}>이메일 등록</button></form></div></div>
        <section className="registry-panel"><div className="registry-section-heading"><h3>설비 대장</h3><span className="registry-help">한 행은 한 대의 설비입니다.</span></div><div className="registry-table-scroll"><table className="registry-table"><thead><tr><th>기종명</th><th>호기</th><th>제조처</th><th>확인 상태</th><th><span className="sr-only">관리</span></th></tr></thead><tbody>{detail.equipment.map((e) => <tr key={e.id}><td>{e.model_name}</td><td className="registry-code">{e.serial_number || '호기 미등록'}</td><td>{e.manufacturing_site || '미확인'}</td><td><span className={`registry-badge ${!e.is_confirmed ? 'review' : ''}`}>{!e.is_active ? '비활성' : e.is_confirmed ? '확인 완료' : e.needs_review ? '소속 확인' : '확인 전'}</span></td><td><button className="registry-text-button" disabled={busy} onClick={() => setEditing(e)} aria-label={`${e.model_name} ${e.serial_number || '호기 미등록'} 수정`}>수정</button></td></tr>)}</tbody></table></div>{!detail.equipment.length && <p className="muted">등록된 설비가 없습니다.</p>}<Pager page={equipmentPage} total={detail.equipment_summary.total} onChange={setEquipmentPage} busy={busy} />
          <EquipmentForm key={`${selected}-${editing?.id || formGeneration}`} editing={editing} busy={busy} onCancel={() => setEditing(null)} onSave={(body) => perform(async () => { await request(`/${selected}/equipment${editing ? `/${editing.id}` : ''}`, auth, editing ? 'PUT' : 'POST', body); setEditing(null); setFormGeneration((n) => n + 1); setEquipmentPage(1) }, '설비 정보를 저장했습니다.')} />
        </section>
        <details className="registry-panel registry-history"><summary>최근 변경 이력</summary><ul>{detail.audit.map((entry, i) => <li key={i}><span>{eventLabels[entry.event] || '관리 정보 변경'}</span><span>{entry.actor_label}</span><time>{new Date(entry.created_at).toLocaleString('ko-KR')}</time></li>)}</ul></details>
      </> : <section className="registry-panel registry-list" aria-label="고객사 목록"><div className="registry-section-heading"><h2>고객사 목록</h2><span className="muted">{list ? `${list.total.toLocaleString()}개 회사` : '조회 중…'}</span></div>{!list ? <p role="status">고객사를 불러오고 있습니다…</p> : <><div className="registry-table-scroll"><table className="registry-table"><thead><tr><th>고객사</th><th>회사코드</th><th>등록 설비</th><th>활성 이메일</th><th>상태</th></tr></thead><tbody>{list.items.map((c) => <tr key={c.id}><td><button className="registry-company-link" disabled={busy} onClick={() => choose(c.id)}>{c.name}<span>상세 보기 ↗</span></button></td><td className="registry-code">{c.code}</td><td>{c.equipment_count}대{c.unconfirmed_count > 0 && <small>확인 전 {c.unconfirmed_count}</small>}</td><td>{c.active_contacts}개</td><td><span className={`registry-badge ${c.is_active ? '' : 'muted'}`}>{c.is_active ? '활성' : '비활성'}</span></td></tr>)}</tbody></table></div>{!list.items.length && <p className="registry-empty">검색 결과가 없습니다.</p>}<Pager page={page} total={list.total} onChange={setPage} busy={busy} /></>}</section>}
    </>}
  </section>
}
