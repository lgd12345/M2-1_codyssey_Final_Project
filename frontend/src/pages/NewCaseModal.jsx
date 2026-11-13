import React, { useEffect, useState } from 'react'
import { SAMPLE_IDS, SCENARIOS } from '../mock/data.js'
import { CALL_REASONS, META } from '../mock/meta.js'
import { caseHref } from '../navigation.js'
import { nowIso } from '../ui.jsx'

// 등록된 장비 목록(시연용). TRUMPF의 "Machine & Machine no." 선택에 해당한다.
const MACHINES = SAMPLE_IDS.map((id) => SCENARIOS[id].intake)
  .filter((m, i, all) => all.findIndex((x) => x.serial === m.serial) === i)
const machineLabel = (m) => `${m.company} · ${m.machine} · ${m.serial}`

const close = () => { window.location.hash = '/cases' }

// TRUMPF "Create new service case": 2단계 모달(1. 사유·기계·오류번호·메시지·이미지 → 2. 연락처).
export function NewCaseModal({ dispatch, nextId }) {
  const [step, setStep] = useState(1)
  const [sampleId, setSampleId] = useState('')
  const [reason, setReason] = useState('')
  const [machineIdx, setMachineIdx] = useState('')
  const [errors, setErrors] = useState([''])
  const [message, setMessage] = useState('')
  const [occurred, setOccurred] = useState('')
  const [files, setFiles] = useState([])
  const [contact, setContact] = useState({ name: '', phone: '', email: '' })

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function loadSample(id) {
    setSampleId(id)
    if (!id) { setReason(''); setMachineIdx(''); setErrors(['']); setMessage(''); setOccurred(''); setContact({ name: '', phone: '', email: '' }); return }
    const s = SCENARIOS[id].intake
    setReason(META[id].type)
    setMachineIdx(String(MACHINES.findIndex((m) => m.serial === s.serial)))
    setErrors(s.alarm && s.alarm !== '알람 없음' ? [s.alarm] : [''])
    setMessage(s.symptom); setOccurred(s.occurred)
    setContact({ name: META[id].creator.split(' ')[0], phone: '010-0000-0000', email: '' })
  }

  const machine = machineIdx === '' ? null : MACHINES[Number(machineIdx)]
  const step1Ready = reason && machine && message.trim()
  const step2Ready = contact.name.trim() && contact.phone.trim()

  function send(e) {
    e.preventDefault()
    const intake = {
      company: machine.company, machine: machine.machine, serial: machine.serial, symptom: message.trim(),
      alarm: errors.map((x) => x.trim()).filter(Boolean).join(', '), occurred, type: reason,
      creator: `${contact.name.trim()} (${machine.company})`, contact,
    }
    dispatch({ type: 'CREATE', intake, sampleId, at: nowIso() })
    window.location.hash = caseHref(nextId).slice(1)
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close() }}>
      <form className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" onSubmit={send}>
        <button type="button" className="modal-x" onClick={close} aria-label="닫기">×</button>
        <h2 id="modal-title">새 서비스 요청</h2>
        <ol className="stepper" aria-label="진행 단계">
          <li className={step === 1 ? 'on' : 'done'}><span>{step > 1 ? '✓' : '1'}</span>요청 내용</li>
          <li className={step === 2 ? 'on' : ''}><span>2</span>연락처</li>
        </ol>

        {step === 1 && (
          <>
            <label className="demo-field">시연용 샘플 불러오기
              <select value={sampleId} onChange={(e) => loadSample(e.target.value)}>
                <option value="">직접 입력 (시연에서는 &lsquo;근거 부족&rsquo; 분석)</option>
                {SAMPLE_IDS.map((id) => <option key={id} value={id}>{SCENARIOS[id].label}</option>)}
              </select>
            </label>
            <label>접수 사유 *<select value={reason} onChange={(e) => setReason(e.target.value)} required><option value="">선택</option>{CALL_REASONS.map((r) => <option key={r}>{r}</option>)}</select></label>
            <label>기계 · 호기 *<select value={machineIdx} onChange={(e) => setMachineIdx(e.target.value)} required><option value="">선택</option>{MACHINES.map((m, i) => <option key={m.serial} value={i}>{machineLabel(m)}</option>)}</select></label>
            <fieldset className="errors"><legend>알람·오류 번호</legend>
              {errors.map((v, i) => <input key={i} value={v} aria-label={`오류 번호 ${i + 1}`} onChange={(e) => setErrors(errors.map((x, j) => (j === i ? e.target.value : x)))} />)}
              <button type="button" className="linkish" onClick={() => setErrors([...errors, ''])}>+ 오류 번호 추가</button>
            </fieldset>
            <label>메시지 *<textarea rows={4} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="어떤 문제가 어떻게 나타나는지 적어 주세요." required /></label>
            <label>사진·동영상 (시연: 저장되지 않음)
              <span className="upload"><span aria-hidden="true">+</span><input type="file" multiple onChange={(e) => setFiles([...e.target.files].map((f) => f.name))} /></span>
            </label>
            {files.length > 0 && <p className="muted small">선택됨: {files.join(', ')}</p>}
            <p className="muted small">* 표시는 필수 항목입니다.</p>
            <div className="modal-actions"><button type="button" onClick={close}>취소</button><button type="button" className="primary" disabled={!step1Ready} onClick={() => setStep(2)}>계속</button></div>
          </>
        )}

        {step === 2 && (
          <>
            <p className="muted small">접수 내용을 확인하고 연락받을 담당자를 입력해 주세요.</p>
            <dl className="kv recap">
              <div><dt>접수 사유</dt><dd>{reason}</dd></div>
              <div><dt>기계 · 호기</dt><dd>{machine && machineLabel(machine)}</dd></div>
              <div><dt>메시지</dt><dd>{message}</dd></div>
            </dl>
            <div className="grid2">
              <label>이름 *<input value={contact.name} onChange={(e) => setContact({ ...contact, name: e.target.value })} required autoFocus /></label>
              <label>전화번호 *<input value={contact.phone} onChange={(e) => setContact({ ...contact, phone: e.target.value })} required /></label>
            </div>
            <label>이메일<input type="email" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} /></label>
            <div className="modal-actions"><button type="button" onClick={() => setStep(1)}>이전</button><button type="submit" className="primary" disabled={!step2Ready}>전송</button></div>
          </>
        )}
      </form>
    </div>
  )
}
