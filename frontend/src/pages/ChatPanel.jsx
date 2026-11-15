import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import { call } from '../api.js'
import { CHIPS, chatOpen, chatPageUrl, draftStateLabel, evidenceFrom, handlerLine, mailDraftUrl, proposalCard, proposalUrl, timeline, toolLabel, toolStatus, transportBody } from '../domain/chat.js'
import { canReanalyze, canStartAnalysis } from '../domain/workflow.js'
import { AnalysisBubble, PendingNotice } from './AnalysisSection.jsx'
import { Modal } from '../ui.jsx'
import { parseMarkdown } from '../domain/markdown.js'

const STATUS_TEXT = { running: '조회 중', done: '완료', failed: '실패' }

// 분석과 대화를 한 창에서: 분석 결과는 대화의 말풍선이고, 분석 시작·재분석·메일 작성은 같은 창의 버튼이다.
// 대화 기록은 서버가 보관하고, 대화 자체는 읽기 전용이다.
export function ChatPanel({ item, csrf, onChanged, dispatch, onAnalyze, analyzing, analysisError }) {
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
        <h2 id="chat-title"><span className="spark" aria-hidden="true">✦</span> AI 분석·대화</h2>
        <span className="muted small">ⓘ AI가 작성한 검토용 초안입니다. 인용된 근거와 원본 매뉴얼을 확인한 뒤 판단해 주세요. 대화는 읽기 전용이며 요청을 바꾸거나 메일을 보내지 않습니다.</span>
      </div>
      {failed && <p className="error" role="alert">대화 기록을 불러오지 못했습니다.</p>}
      {!failed && !initial && <p className="muted" role="status">대화를 불러오는 중…</p>}
      {initial && <ChatSession key={item.id} item={item} csrf={csrf} initial={initial} onChanged={onChanged} dispatch={dispatch} onAnalyze={onAnalyze} analyzing={analyzing} analysisError={analysisError} />}
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

function ChatSession({ item, csrf, initial, onChanged, dispatch, onAnalyze, analyzing, analysisError }) {
  const transport = useMemo(() => new DefaultChatTransport({
    api: `/api/v1/service-requests/${item.id}/chat`, credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf },
    prepareSendMessagesRequest: ({ id, messages, trigger }) => ({ body: transportBody({ id, messages, trigger }) }),
  }), [item.id, csrf])
  const { messages, sendMessage, status, error, stop, clearError } = useChat({ id: item.id, messages: initial.messages, transport, onFinish: () => onChanged?.() })
  const [text, setText] = useState('')
  const end = useRef(null)
  const busy = status === 'submitted' || status === 'streaming'
  const open = chatOpen(item)
  const turns = messages.filter((m) => m.role === 'user').length
  const full = turns >= initial.limit
  // Follow new messages, but never jump past the analysis when the page first opens.
  const opened = useRef(false)
  useEffect(() => {
    if (opened.current) end.current?.scrollIntoView?.({ block: 'nearest' })
    opened.current = true
  }, [messages.length, status])
  const history = item.analysisHistory ?? (item.analysis ? [{ revision: 1, at: null, analysis: item.analysis }] : [])
  // Messages that just streamed in carry no server time: stamp them when first seen so they stay in order against analyses.
  const seen = useRef(new Map())
  const stamped = messages.map((m) => {
    if (m.metadata?.pydantic_ai?.timestamp) return m
    if (!seen.current.has(m.id)) seen.current.set(m.id, new Date().toISOString())
    return { ...m, metadata: { ...m.metadata, pydantic_ai: { timestamp: seen.current.get(m.id) } } }
  })
  const entries = timeline(stamped, history)
  const startable = canStartAnalysis(item) && Boolean(onAnalyze)
  const again = canReanalyze(item) && Boolean(dispatch)
  function send(value) {
    const question = value.trim()
    if (!question || busy || full || !open) return
    clearError()
    sendMessage({ text: question })
    setText('')
  }

  return (
    <div className="chat-box">
      <div className="chat-log" role="log" aria-live="polite" aria-label="AI 대화 내용">
        {!item.analysis && <div className="chat-msg assistant"><PendingNotice item={item} error={analysisError} /></div>}
        {open && entries.length === 0 && <p className="muted">아래 버튼을 누르거나 질문을 입력해 보세요. 예: 비슷한 과거 사례는 누가 담당했어?</p>}
        {entries.map((entry) => entry.kind === 'analysis' ? (
          <div key={`analysis-${entry.revision}`} className="chat-msg assistant analysis">
            {entry.current ? <AnalysisBubble analysis={entry.analysis} item={item} current revision={entry.revision} dispatch={dispatch} csrf={csrf} onChanged={onChanged} />
              : <details><summary>이전 분석 ({entry.revision}회차) 보기</summary><AnalysisBubble analysis={entry.analysis} item={item} current={false} revision={entry.revision} /></details>}
          </div>
        ) : <Turn key={entry.id} turn={entry} itemId={item.id} />)}
        {(item.proposals ?? []).length > 0 && <Proposals item={item} csrf={csrf} onChanged={onChanged} />}
        {(item.mailDrafts ?? []).length > 0 && <MailDrafts item={item} csrf={csrf} onChanged={onChanged} />}
        {status === 'submitted' && <p className="muted small" role="status">AI가 확인하는 중…</p>}
        <div ref={end} />
      </div>
      {error && <p className="error" role="alert">{friendly(error)}</p>}
      <div className="chips" aria-label="추천 질문">
        {startable && <button type="button" className="pill primary-pill" disabled={analyzing} onClick={() => onAnalyze(item.id)}>{analyzing ? '분석 요청 중…' : item.analysisRun?.status === 'failed' ? '분석 다시 시도' : '분석해줘'}</button>}
        {again && <button type="button" className="pill" onClick={() => dispatch({ type: 'REANALYZE', id: item.id })}>재분석</button>}
        {open && CHIPS.map((chip) => <button key={chip.label} type="button" className="pill" disabled={busy || full} onClick={() => send(chip.text)}>{chip.label}</button>)}
      </div>
      <form className="chat-form" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <textarea rows={2} maxLength={2000} value={text} aria-label="질문 입력" placeholder={open ? 'AI에게 질문하기' : '분석이 끝나면 질문할 수 있습니다'} disabled={full || !open}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(text) } }} />
        <div className="actions">
          <span className="muted small">질문 {turns}/{initial.limit}</span>
          {busy ? <button type="button" className="ghost" onClick={stop}>중지</button>
            : <button type="submit" className="primary" disabled={!text.trim() || full || !open}>보내기</button>}
        </div>
      </form>
    </div>
  )
}

// 에이전트가 제안한 변경(추가 정보 저장, 재분석). 제안만 기록되어 있고, 확인 버튼을 눌러야 실행된다.
function Proposals({ item, csrf, onChanged }) {
  return (
    <div className="proposals" aria-label="AI 제안">
      {item.proposals.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} itemId={item.id} csrf={csrf} onChanged={onChanged} />)}
    </div>
  )
}

function ProposalCard({ proposal, itemId, csrf, onChanged }) {
  const card = proposalCard(proposal)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function decide(action) {
    setBusy(true); setError('')
    try { await call(proposalUrl(itemId, proposal.id, action), { method: 'POST', body: {}, csrf }) } catch (e) { setError(e.message) }
    await onChanged?.()
    setBusy(false)
  }
  return (
    <section className="proposal-card" aria-label={card.title}>
      <h3>{card.title} <span className={`lozenge status-${proposal.status}`}>{card.state}</span></h3>
      {card.detail && <p className="chat-text">{card.detail}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {card.open && (
        <div className="actions">
          <button type="button" className="ghost" disabled={busy} onClick={() => decide('cancel')}>취소</button>
          <button type="button" className="primary" disabled={busy} onClick={() => decide('confirm')}>{card.confirm}</button>
        </div>
      )}
    </section>
  )
}

// 에이전트가 만든 부서 메일 초안. 보내기 버튼을 눌러야만 발송됩니다(수신 주소는 서버가 부서 정보에서 찾습니다).
function MailDrafts({ item, csrf, onChanged }) {
  return (
    <div className="mail-drafts" aria-label="부서 메일">
      {item.mailDrafts.map((draft) => <MailCard key={draft.id} draft={draft} itemId={item.id} csrf={csrf} onChanged={onChanged} />)}
    </div>
  )
}

function MailCard({ draft, itemId, csrf, onChanged }) {
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const open = draft.status === 'draft' || draft.status === 'failed'
  async function act(action) {
    setBusy(true); setError('')
    try {
      await call(mailDraftUrl(itemId, draft.id, action), { method: 'POST', body: action === 'send' ? { subject, body } : {}, csrf })
    } catch (e) { setError(e.message) }
    await onChanged?.()
    setBusy(false)
  }
  return (
    <section className="mail-card" aria-label={`${draft.departmentName} 메일`}>
      <h3>{draft.departmentName} 메일 <span className={`lozenge status-${draft.status}`}>{draftStateLabel(draft.status)}</span></h3>
      <p className="mail-to"><strong>받는 사람</strong> {draft.departmentName} · {draft.recipients.join(', ')}</p>
      {open ? (
        <>
          <input aria-label="메일 제목" value={subject} maxLength={150} onChange={(e) => setSubject(e.target.value)} />
          <textarea aria-label="메일 본문" rows={6} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)} />
          {error && <p className="error" role="alert">{error}</p>}
          <div className="actions">
            <button type="button" className="ghost" disabled={busy} onClick={() => act('cancel')}>취소</button>
            <button type="button" className="primary" disabled={busy || !subject.trim() || !body.trim()} onClick={() => act('send')}>보내기</button>
          </div>
        </>
      ) : <><p><strong>{draft.subject}</strong></p><p className="chat-text">{draft.body}</p></>}
    </section>
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
      {answer && <Markdown text={answer} />}
      <Evidence parts={turn.parts} itemId={itemId} />
    </div>
  )
}

// 답변은 작은 마크다운 해석기로 보여준다: 굵게·코드·목록·제목·구분선만, HTML이나 링크는 해석하지 않는다.
function Markdown({ text }) {
  const inline = (parts) => parts.map((p, i) => p.t === 'bold' ? <strong key={i}>{p.v}</strong> : p.t === 'code' ? <code key={i}>{p.v}</code> : <React.Fragment key={i}>{p.v}</React.Fragment>)
  return (
    <div className="chat-text markdown">
      {parseMarkdown(text).map((b, i) => {
        if (b.type === 'hr') return <hr key={i} />
        if (b.type === 'h') return <p key={i} className="md-heading"><strong>{inline(b.inlines)}</strong></p>
        if (b.type === 'ul') return <ul key={i}>{b.items.map((item, j) => <li key={j}>{inline(item)}</li>)}</ul>
        if (b.type === 'ol') return <ol key={i}>{b.items.map((item, j) => <li key={j}>{inline(item)}</li>)}</ol>
        return <p key={i}>{inline(b.inlines)}</p>
      })}
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
