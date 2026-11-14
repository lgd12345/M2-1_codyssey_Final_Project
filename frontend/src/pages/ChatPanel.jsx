import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import { call } from '../api.js'
import { CHIPS, chatPageUrl, evidenceFrom, groupTurns, handlerLine, toolLabel, toolStatus, transportBody } from '../domain/chat.js'
import { Modal } from '../ui.jsx'

const STATUS_TEXT = { running: '조회 중', done: '완료', failed: '실패' }

// 운영진이 요청 하나에 대해 AI에게 묻는 대화. 읽기 전용이며 대화 기록은 서버가 보관한다.
export function ChatPanel({ item, csrf }) {
  const [initial, setInitial] = useState(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    call(`/service-requests/${item.id}/chat`).then((data) => { if (live) setInitial(data) }).catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [item.id])
  return (
    <section className="block chat" aria-labelledby="chat-title">
      <div className="block-head">
        <h2 id="chat-title"><span className="spark" aria-hidden="true">✦</span> AI 대화</h2>
        <span className="muted small">ⓘ 읽기 전용입니다. 요청을 바꾸거나 메일을 보내지 않습니다.</span>
      </div>
      {failed && <p className="error" role="alert">대화 기록을 불러오지 못했습니다.</p>}
      {!failed && !initial && <p className="muted" role="status">대화를 불러오는 중…</p>}
      {initial && <ChatSession key={item.id} item={item} csrf={csrf} initial={initial} />}
    </section>
  )
}

function friendly(error) {
  try {
    const body = JSON.parse(error.message)
    if (typeof body?.detail === 'string') return body.detail
  } catch { /* not JSON */ }
  return error.message && error.message.length < 200 ? error.message : '답변을 받지 못했습니다. 다시 시도해 주세요.'
}

function ChatSession({ item, csrf, initial }) {
  const transport = useMemo(() => new DefaultChatTransport({
    api: `/api/v1/service-requests/${item.id}/chat`, credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf },
    prepareSendMessagesRequest: ({ id, messages, trigger }) => ({ body: transportBody({ id, messages, trigger }) }),
  }), [item.id, csrf])
  const { messages, sendMessage, status, error, stop, clearError } = useChat({ id: item.id, messages: initial.messages, transport })
  const [text, setText] = useState('')
  const end = useRef(null)
  const busy = status === 'submitted' || status === 'streaming'
  const turns = messages.filter((m) => m.role === 'user').length
  const full = turns >= initial.limit
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'nearest' }) }, [messages, status])

  function send(value) {
    const question = value.trim()
    if (!question || busy || full) return
    clearError()
    sendMessage({ text: question })
    setText('')
  }

  return (
    <div className="chat-box">
      <div className="chat-log" role="log" aria-live="polite" aria-label="AI 대화 내용">
        {messages.length === 0 && <p className="muted">아래 버튼을 누르거나 질문을 입력해 보세요. 예: 비슷한 과거 사례는 누가 담당했어?</p>}
        {groupTurns(messages).map((turn) => <Turn key={turn.id} turn={turn} itemId={item.id} />)}
        {status === 'submitted' && <p className="muted small" role="status">AI가 확인하는 중…</p>}
        <div ref={end} />
      </div>
      {error && <p className="error" role="alert">{friendly(error)}</p>}
      <div className="chips" aria-label="추천 질문">
        {CHIPS.map((chip) => <button key={chip.label} type="button" className="pill" disabled={busy || full} onClick={() => send(chip.text)}>{chip.label}</button>)}
      </div>
      <form className="chat-form" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <textarea rows={2} maxLength={2000} value={text} aria-label="질문 입력" placeholder="AI에게 질문하기" disabled={full}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(text) } }} />
        <div className="actions">
          <span className="muted small">질문 {turns}/{initial.limit}</span>
          {busy ? <button type="button" className="ghost" onClick={stop}>중지</button>
            : <button type="submit" className="primary" disabled={!text.trim() || full}>보내기</button>}
        </div>
      </form>
    </div>
  )
}

function Turn({ turn, itemId }) {
  if (turn.role === 'user') {
    return <div className="chat-msg user"><p>{turn.parts.filter((p) => p.type === 'text').map((p) => p.text).join('')}</p></div>
  }
  const tools = turn.parts.filter((p) => typeof p.type === 'string' && p.type.startsWith('tool-'))
  const answer = turn.parts.filter((p) => p.type === 'text').map((p) => p.text).join('')
  return (
    <div className="chat-msg assistant">
      {tools.length > 0 && (
        <ul className="chat-tools" aria-label="조회 과정">
          {tools.map((p) => { const s = toolStatus(p); return <li key={p.toolCallId} className={s}>{toolLabel(p.type.slice(5))} · {STATUS_TEXT[s]}</li> })}
        </ul>
      )}
      {answer && <p className="chat-text">{answer}</p>}
      <Evidence parts={turn.parts} itemId={itemId} />
    </div>
  )
}

function Evidence({ parts, itemId }) {
  const { cases, documents, handlers } = evidenceFrom(parts)
  const [view, setView] = useState(null)
  if (!cases.length && !documents.length && !handlers.length) return null
  return (
    <div className="chat-evidence">
      {cases.length > 0 && (
        <details><summary>과거 사례 {cases.length}건 (보기)</summary>
          <ul>{cases.map((c) => <li key={c.fsr_no}><strong>{c.fsr_no}</strong> · {c.machine}<br /><span className="muted small">{c.complaint}</span>{c.resolution && <><br /><span className="small">조치: {c.resolution}</span></>}</li>)}</ul>
        </details>
      )}
      {handlers.length > 0 && (
        <details open><summary>사례 담당 기록 {handlers.length}건</summary>
          <ul>{handlers.map((h) => <li key={h.fsr_no}>{handlerLine(h)}</li>)}</ul>
          <p className="muted small">작업자 ID는 가명입니다. 운영진 화면에서만 표시합니다.</p>
        </details>
      )}
      {documents.length > 0 && (
        <details><summary>관련 문서 {documents.length}건 (보기)</summary>
          <ul>{documents.map((d) => <li key={`${d.sha}:${d.page}`}>{d.label} <button type="button" className="ghost small" onClick={() => setView(d)}>원본 페이지 보기</button></li>)}</ul>
        </details>
      )}
      {view && (
        <Modal title={`원본 페이지 · ${view.label}`} onClose={() => setView(null)}>
          <img className="source-page" src={chatPageUrl(itemId, view.sha, view.page)} alt={`${view.label} 원본 페이지`} />
        </Modal>
      )}
    </div>
  )
}
