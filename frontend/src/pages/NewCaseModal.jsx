import React, { useEffect, useRef, useState } from 'react'
import { CALL_REASONS } from '../domain/catalog.js'
import { caseHref, portalHref } from '../navigation.js'

const machineLabel = machine => `${machine.company} · ${machine.machine} · ${machine.serial}`

export function NewCaseModal({ onCreate, equipment = [], portal = false }) {
  const home = portal ? '/portal' : '/cases'
  const [step, setStep] = useState(1)
  const [reason, setReason] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [alarms, setAlarms] = useState([''])
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
        alarm_numbers: alarms.map(value => value.trim()).filter(Boolean), contact })
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
        {equipment.length === 0 && <p className="notice warn" role="status">접수할 수 있는 등록 장비가 없습니다. 고객사 소속과 장비 등록 정보를 관리자에게 확인해 주세요.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {step === 1 ? <>
          <label>접수 사유 *<select value={reason} onChange={event => setReason(event.target.value)} required><option value="">선택</option>{CALL_REASONS.map(value => <option key={value}>{value}</option>)}</select></label>
          <label>기계 · 호기 *<select value={equipmentId} onChange={event => setEquipmentId(event.target.value)} required disabled={!equipment.length}><option value="">선택</option>{equipment.map(item => <option key={item.id} value={item.id}>{machineLabel(item)}</option>)}</select></label>
          <fieldset className="errors"><legend>알람·오류 번호</legend>
            {alarms.map((value, index) => <input key={index} value={value} maxLength={80} aria-label={`오류 번호 ${index + 1}`} onChange={event => setAlarms(alarms.map((old, at) => at === index ? event.target.value : old))} />)}
            <button type="button" className="linkish" disabled={alarms.length >= 20} onClick={() => setAlarms([...alarms, ''])}>+ 오류 번호 추가</button>
          </fieldset>
          <label>메시지 *<textarea rows={4} maxLength={10000} value={message} onChange={event => setMessage(event.target.value)} placeholder="어떤 문제가 어떻게 나타나는지 적어 주세요." required /></label>
          <label>사진·동영상<span className="upload"><span aria-hidden="true">+</span><input type="file" multiple disabled aria-describedby="upload-not-connected" /></span></label>
          <p id="upload-not-connected" className="muted small">첨부 저장 기능은 아직 연결되지 않았습니다.</p>
          <p className="muted small">* 표시는 필수 항목입니다.</p>
          <div className="modal-actions"><button type="button" onClick={close}>취소</button><button type="button" className="primary" disabled={!step1Ready} onClick={() => setStep(2)}>계속</button></div>
        </> : <>
          <p className="muted small">접수 내용을 확인하고 연락받을 담당자를 입력해 주세요.</p>
          <dl className="kv recap"><div><dt>접수 사유</dt><dd>{reason}</dd></div><div><dt>기계 · 호기</dt><dd>{machine && machineLabel(machine)}</dd></div><div><dt>메시지</dt><dd>{message}</dd></div></dl>
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
