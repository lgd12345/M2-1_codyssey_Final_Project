import React, { useEffect, useRef, useState } from 'react'
import { CALL_REASONS } from '../domain/catalog.js'
import { caseHref, portalHref } from '../navigation.js'
import { ModelPicker } from './ModelPicker.jsx'

const machineLabel = machine => machine.machine

export function NewCaseModal({ onCreate, equipment = [], portal = false }) {
  const home = portal ? '/portal' : '/cases'
  const [step, setStep] = useState(1)
  const [reason, setReason] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [message, setMessage] = useState('')
  const [contact, setContact] = useState({ name: '', phone: '', email: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submitting = useRef(false)
  const close = () => { if (!submitting.current) window.location.hash = home }
  const machine = equipment.find(item => item.id === equipmentId)
  const step1Ready = reason && machine && message.trim()
  const step2Ready = contact.name.trim() && contact.phone.trim()

  useEffect(() => {
    const onKey = event => { if (event.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [home])

  async function send(event) {
    event.preventDefault()
    if (step !== 2 || !step1Ready || !step2Ready || submitting.current) return
    submitting.current = true; setBusy(true); setError('')
    try {
      const created = await onCreate({ equipment_id: machine.id, reason, message: message.trim(),
        contact })
      window.location.hash = (portal ? portalHref(created.id) : caseHref(created.id)).slice(1)
    } catch (failure) { setError(failure.message) }
    finally { submitting.current = false; setBusy(false) }
  }

  return (
    <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) close() }}>
      <form className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" onSubmit={send} aria-busy={busy}>
        <button type="button" className="modal-x" onClick={close} disabled={busy} aria-label="닫기">×</button>
        <h2 id="modal-title">새 서비스 요청</h2>
        <ol className="stepper" aria-label="진행 단계">
          <li className={step === 1 ? 'on' : 'done'}><span>{step > 1 ? '✓' : '1'}</span>요청 내용</li>
          <li className={step === 2 ? 'on' : ''}><span>2</span>연락처</li>
        </ol>
        {equipment.length === 0 && <p className="notice warn" role="status">선택할 수 있는 기종이 없습니다. 고객사 소속과 기종 등록 정보를 관리자에게 확인해 주세요.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {step === 1 ? <>
          <label>접수 사유 *<select value={reason} onChange={event => setReason(event.target.value)} required><option value="">선택</option>{CALL_REASONS.map(value => <option key={value}>{value}</option>)}</select></label>
          <ModelPicker models={equipment} value={equipmentId} onChange={setEquipmentId} />
          <label>메시지 *<textarea rows={4} maxLength={10000} value={message} onChange={event => setMessage(event.target.value)} placeholder="예: 공구 교환 중 ATC가 멈춥니다. 발생 시점, 알람 번호, 반복 여부를 적어 주세요." required /></label>
          <p className="muted small">* 표시는 필수 항목입니다.</p>
          <div className="modal-actions"><button type="button" onClick={close}>취소</button><button type="button" className="primary" disabled={!step1Ready} onClick={event => { event.preventDefault(); setStep(2) }}>계속</button></div>
        </> : <>
          <p className="muted small">접수 내용을 확인하고 연락받을 담당자를 입력해 주세요.</p>
          <dl className="kv recap"><div><dt>접수 사유</dt><dd>{reason}</dd></div><div><dt>기종</dt><dd>{machine && machineLabel(machine)}</dd></div><div><dt>메시지</dt><dd>{message}</dd></div></dl>
          <div className="grid2">
            <label>이름 *<input value={contact.name} maxLength={80} onChange={event => setContact({ ...contact, name: event.target.value })} required autoFocus disabled={busy} /></label>
            <label>전화번호 *<input value={contact.phone} maxLength={40} onChange={event => setContact({ ...contact, phone: event.target.value })} required disabled={busy} /></label>
          </div>
          <label>이메일<input type="email" value={contact.email} maxLength={254} onChange={event => setContact({ ...contact, email: event.target.value })} disabled={busy} /></label>
          <div className="modal-actions"><button type="button" disabled={busy} onClick={() => setStep(1)}>이전</button><button type="submit" className="primary" disabled={busy || !step1Ready || !step2Ready}>{busy ? '접수 중…' : '전송'}</button></div>
        </>}
      </form>
    </div>
  )
}
