import React, { useCallback, useEffect, useState } from 'react'
import { call } from '../api.js'
import { departmentChange, isValidKey, parseRecipients } from '../domain/departments.js'
import { formatTime } from '../ui.jsx'

// 메일을 보낼 수 있는 부서와 수신 주소. 수신 주소는 서버 설정이 아니라 DB 데이터이며 여기서 바꾼다.
export function Departments({ csrf }) {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => call('/service-requests/departments/manage').then((d) => setRows(d.departments)).catch((e) => setError(e.message)), [])
  useEffect(() => { load() }, [load])
  return (
    <section className="center-card departments" aria-labelledby="dept-title">
      <h1 id="dept-title">부서 메일 설정</h1>
      <p className="muted">권장 활동의 메일 작성은 여기 등록된 주소로 발송됩니다. 주소가 없거나 사용 안 함인 부서에는 메일을 보낼 수 없습니다.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!rows && !error && <p className="muted" role="status">불러오는 중…</p>}
      {rows && <ul className="dept-list">{rows.map((row) => <DepartmentRow key={row.key} row={row} csrf={csrf} onSaved={setRows} />)}</ul>}
      {rows && <NewDepartment csrf={csrf} onSaved={setRows} />}
    </section>
  )
}

function DepartmentRow({ row, csrf, onSaved }) {
  const [draft, setDraft] = useState({ name: row.name, description: row.description, recipientsText: row.recipients.join('\n'), active: row.active })
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const parsed = parseRecipients(draft.recipientsText)
  const change = departmentChange(row, draft)
  const set = (field) => (e) => setDraft({ ...draft, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  async function save() {
    setError(''); setMessage('')
    try {
      const data = await call(`/service-requests/departments/${row.key}`, { method: 'PATCH', body: change, csrf })
      const saved = data.departments.find((d) => d.key === row.key)
      setDraft({ name: saved.name, description: saved.description, recipientsText: saved.recipients.join('\n'), active: saved.active })  // show what the server kept
      onSaved(data.departments); setMessage('저장했습니다.')
    } catch (e) { setError(e.message) }
  }
  return (
    <li className="dept-row" aria-label={`${row.name} 부서`}>
      <h2>{row.name} <small className="muted">({row.key})</small></h2>
      <label>이름<input value={draft.name} maxLength={40} onChange={set('name')} /></label>
      <label>언제 보내나<input value={draft.description} maxLength={300} onChange={set('description')} /></label>
      <label>수신 주소 (한 줄에 하나)<textarea rows={3} value={draft.recipientsText} onChange={set('recipientsText')} /></label>
      {parsed.invalid.length > 0 && <p className="error" role="alert">주소 형식이 올바르지 않습니다: {parsed.invalid.join(', ')}</p>}
      <label className="check"><input type="checkbox" checked={draft.active} onChange={set('active')} /> 사용</label>
      <div className="actions">
        {row.updatedBy && <span className="muted small">마지막 변경 {row.updatedBy} · {formatTime(row.updatedAt)}</span>}
        <button type="button" className="primary" disabled={!Object.keys(change).length || parsed.invalid.length > 0 || !draft.name.trim()} onClick={save}>저장</button>
      </div>
      {message && <p className="notice ok" role="status">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </li>
  )
}

function NewDepartment({ csrf, onSaved }) {
  const [form, setForm] = useState({ key: '', name: '', description: '', recipientsText: '' })
  const [error, setError] = useState('')
  const parsed = parseRecipients(form.recipientsText)
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value })
  async function add() {
    setError('')
    try {
      const data = await call('/service-requests/departments', { method: 'POST', csrf,
        body: { key: form.key, name: form.name.trim(), description: form.description.trim(), recipients: parsed.list } })
      onSaved(data.departments); setForm({ key: '', name: '', description: '', recipientsText: '' })
    } catch (e) { setError(e.message) }
  }
  return (
    <section className="dept-new" aria-label="부서 추가">
      <h2>부서 추가</h2>
      <label>키 (영문 소문자·숫자·_)<input value={form.key} maxLength={31} onChange={set('key')} /></label>
      <label>이름<input value={form.name} maxLength={40} onChange={set('name')} /></label>
      <label>언제 보내나<input value={form.description} maxLength={300} onChange={set('description')} /></label>
      <label>수신 주소 (한 줄에 하나)<textarea rows={2} value={form.recipientsText} onChange={set('recipientsText')} /></label>
      {parsed.invalid.length > 0 && <p className="error" role="alert">주소 형식이 올바르지 않습니다: {parsed.invalid.join(', ')}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions"><button type="button" className="primary" disabled={!isValidKey(form.key) || !form.name.trim() || parsed.invalid.length > 0} onClick={add}>부서 추가</button></div>
    </section>
  )
}
