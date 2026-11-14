import React, { useEffect, useRef, useState } from 'react'
import { CALL_REASONS } from '../domain/catalog.js'
import { caseHref, portalHref } from '../navigation.js'
import { ModelPicker } from './ModelPicker.jsx'

export function NewCaseModal({ onCreate, equipment = [], portal = false }) {
  const home = portal ? '/portal' : '/cases'
  const [reason, setReason] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submitting = useRef(false)
  const close = () => { if (!submitting.current) window.location.hash = home }
  const ready = reason && equipment.some(item => item.id === equipmentId) && message.trim()

  useEffect(() => {
    const onKey = event => { if (event.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [home])

  async function send(event) {
    event.preventDefault()
    if (!ready || submitting.current) return
    submitting.current = true; setBusy(true); setError('')
    try {
      const created = await onCreate({ equipment_id: equipmentId, reason, message: message.trim() })
      window.location.hash = (portal ? portalHref(created.id) : caseHref(created.id)).slice(1)
    } catch (failure) { setError(failure.message) }
    finally { submitting.current = false; setBusy(false) }
  }

  return (
    <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) close() }}>
      <form className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" onSubmit={send} aria-busy={busy}>
        <button type="button" className="modal-x" onClick={close} disabled={busy} aria-label="닫기">×</button>
        <h2 id="modal-title">새 서비스 요청</h2>
        {equipment.length === 0 && <p className="notice warn" role="status">선택할 수 있는 기종이 없습니다. 고객사 소속과 기종 등록 정보를 관리자에게 확인해 주세요.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <label>접수 사유 *<select value={reason} onChange={event => setReason(event.target.value)} required disabled={busy}><option value="">선택</option>{CALL_REASONS.map(value => <option key={value}>{value}</option>)}</select></label>
        <ModelPicker models={equipment} value={equipmentId} onChange={setEquipmentId} disabled={busy} />
        <label>메시지 *<textarea rows={4} maxLength={10000} value={message} onChange={event => setMessage(event.target.value)} placeholder="예: 공구 교환 중 ATC가 멈춥니다. 발생 시점, 알람 번호, 반복 여부를 적어 주세요." required disabled={busy} /></label>
        <p className="muted small">* 표시는 필수 항목입니다. 접수자는 로그인한 계정으로 기록됩니다.</p>
        <div className="modal-actions"><button type="button" onClick={close} disabled={busy}>취소</button><button type="submit" className="primary" disabled={busy || !ready}>{busy ? '접수 중…' : '전송'}</button></div>
      </form>
    </div>
  )
}
