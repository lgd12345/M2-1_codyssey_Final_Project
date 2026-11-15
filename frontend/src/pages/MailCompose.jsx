import React, { useEffect, useRef, useState } from 'react'
import { call } from '../api.js'
import { mailAiUrl, mailTemplateUrl } from '../domain/analysis.js'
import { mailDraftUrl } from '../domain/chat.js'

// 권장 활동 아래에 펼쳐지는 메일 작성 영역. 고정 양식으로 미리 채워 열리며(AI 호출 없음), \`AI로 작성\`을 누르면 에이전트가 채운다.
// 펼치기만 해서는 아무것도 저장·발송되지 않고, 보내기를 눌러야 초안이 저장되고 발송된다. 접으면 흔적 없이 닫힌다.
// 수신 주소는 서버가 부서 정보에서 찾는다.
export function MailCompose({ item, departmentKey, csrf, onSent, onChanged }) {
  const [form, setForm] = useState(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const draftId = useRef(null)
  useEffect(() => {
    let live = true
    call(mailTemplateUrl(item.id, departmentKey)).then((data) => {
      if (!live) return
      setForm(data); setSubject(data.subject); setBody(data.body)
    }).catch((e) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [item.id, departmentKey])

  async function aiCompose() {
    setBusy('ai'); setError('')
    try {
      const data = await call(mailAiUrl(item.id), { method: 'POST', body: { department_key: departmentKey, instruction }, csrf })
      setSubject(data.subject); setBody(data.body)
    } catch (e) { setError(e.message) }
    setBusy('')
  }

  async function sendMail() {
    setBusy('send'); setError('')
    try {
      if (draftId.current === null) {
        const made = await call(`/service-requests/${item.id}/mail-drafts`, { method: 'POST', body: { department_key: departmentKey, subject, body }, csrf })
        draftId.current = made.id
      }
      await call(mailDraftUrl(item.id, draftId.current, 'send'), { method: 'POST', body: { subject, body }, csrf })
      await onChanged?.()
      onSent?.()
      return
    } catch (e) { setError(e.message) }
    await onChanged?.()
    setBusy('')
  }

  return (
    <section className="mail-compose" aria-label={`${form?.departmentName ?? ''} 메일 작성`.trim()}>
      {!form && !error && <p className="muted" role="status">메일 양식을 불러오는 중…</p>}
      {form && (
        <>
          <p className="mail-to"><strong>받는 사람</strong> {form.departmentName} · {form.recipients.join(', ')}</p>
          <label>제목<input aria-label="메일 제목" value={subject} maxLength={150} disabled={Boolean(busy)} onChange={(e) => setSubject(e.target.value)} /></label>
          <label>본문<textarea aria-label="메일 본문" rows={12} maxLength={4000} value={body} disabled={Boolean(busy)} onChange={(e) => setBody(e.target.value)} /></label>
          <div className="ai-compose">
            <input aria-label="AI에게 요청(선택)" placeholder="AI에게 요청(선택): 예) 긴급 건임을 강조" value={instruction} maxLength={500} disabled={Boolean(busy)} onChange={(e) => setInstruction(e.target.value)} />
            <button type="button" className="ai-button" disabled={Boolean(busy)} onClick={aiCompose}>{busy === 'ai' ? 'AI가 작성하는 중…' : 'AI로 작성'}</button>
          </div>
        </>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        <button type="button" className="primary" disabled={!form || Boolean(busy) || !subject.trim() || !body.trim()} onClick={sendMail}>{busy === 'send' ? '보내는 중…' : '보내기'}</button>
      </div>
    </section>
  )
}
