import React, { useState } from 'react'
import { Avatar, formatTime, nowIso } from '../ui.jsx'

// Jira의 Activity: 전체/댓글/이력 보기, "Add internal note / Reply to customer" 입력줄,
// 내부 메모는 노란 배경과 자물쇠 표시, 입력 영역의 Suggest reply·상황별 알약(contextual pills).
const SHOW = [{ key: 'all', label: '전체' }, { key: 'comments', label: '댓글' }, { key: 'history', label: '이력' }]
const CUSTOMER_SAMPLE = '주축 쪽에서 저속으로 돌릴 때 갈리는 소리가 납니다.'

export function Activity({ item, dispatch, me }) {
  const [show, setShow] = useState('all')
  const [mode, setMode] = useState(null) // 'internal' | 'public'
  const [text, setText] = useState('')
  const a = item.analysis

  const pills = mode === 'public' ? [
    item.status === '추가 정보 필요' && a?.questions.length ? { label: '추가 정보 요청', text: `안녕하세요. 정확한 확인을 위해 아래 내용을 알려 주세요.\n${a.questions.map((q) => `- ${q}`).join('\n')}` } : null,
    { label: '후속 연락', text: '안녕하세요. 접수하신 건의 진행 상황을 안내드립니다. 추가로 확인이 필요한 내용이 있으면 연락드리겠습니다.' },
  ].filter(Boolean) : []

  function send() {
    dispatch({ type: 'ADD_COMMENT', id: item.id, kind: mode, text, by: me, at: nowIso() })
    setText(''); setMode(null)
  }

  const entries = [
    ...item.comments.map((c) => ({ ...c, entry: 'comment' })),
    ...item.history.map((h, i) => ({ id: `h${i}`, at: h.at, text: h.text, entry: 'history' })),
  ].filter((e) => show === 'all' || (show === 'comments' ? e.entry === 'comment' : e.entry === 'history'))
    .sort((x, y) => (x.at < y.at ? 1 : x.at > y.at ? -1 : 0))

  return (
    <section className="block" aria-labelledby="activity-title">
      <div className="block-head"><h2 id="activity-title">활동</h2></div>
      <div className="show-row" role="tablist" aria-label="활동 보기">
        <span className="muted small">보기:</span>
        {SHOW.map((s) => <button key={s.key} role="tab" aria-selected={show === s.key} className={show === s.key ? 'quick-btn active' : 'quick-btn'} onClick={() => setShow(s.key)}>{s.label}</button>)}
      </div>

      <div className="comment-bar">
        <Avatar name={me} />
        {mode === null ? (
          <div className="bar-closed"><button className="linkish" onClick={() => setMode('internal')}>내부 메모 추가</button><span aria-hidden="true">/</span><button className="linkish" onClick={() => setMode('public')}>고객에게 답변</button></div>
        ) : (
          <div className="editor">
            <p className="muted small">{mode === 'internal' ? '내부 메모: 우리 팀만 볼 수 있습니다.' : '고객에게 답변: 접수자에게 전달됩니다. (시연: 실제 전송 없음)'}</p>
            <textarea rows={4} value={text} autoFocus onChange={(e) => setText(e.target.value)} aria-label={mode === 'internal' ? '내부 메모' : '고객 답변'} />
            <div className="editor-tools">
              {mode === 'public' && a && <button className="pill" onClick={() => setText(`안녕하세요. 접수하신 건을 확인했습니다.\n${a.summary}\n담당자가 곧 연락드리겠습니다.`)}>✦ 답변 제안</button>}
              {pills.map((p) => <button key={p.label} className="pill" onClick={() => setText(p.text)}>{p.label}</button>)}
            </div>
            <div className="actions"><button className="ghost" onClick={() => { setMode(null); setText('') }}>취소</button><button className="primary" disabled={!text.trim()} onClick={send}>저장</button></div>
          </div>
        )}
      </div>

      {item.status === '추가 정보 필요' && (
        <div className="demo-box">
          <p className="small"><strong>시연용</strong> 고객이 추가 정보를 답한 상황을 만들어 재분석 흐름을 볼 수 있습니다.</p>
          <button className="ghost small" onClick={() => dispatch({ type: 'CUSTOMER_REPLY', id: item.id, text: CUSTOMER_SAMPLE, at: nowIso() })}>고객 답변 받기 → 재분석</button>
        </div>
      )}

      <ul className="activity">
        {entries.map((e) => e.entry === 'history' ? (
          <li key={e.id} className="event"><time>{formatTime(e.at)}</time> {e.text}</li>
        ) : (
          <li key={e.id} className={e.kind === 'internal' ? 'comment internal' : 'comment'}>
            <Avatar name={e.by} />
            <div>
              <p className="comment-meta"><strong>{e.by}</strong> {formatTime(e.at)}
                {e.kind === 'internal' && <span className="lock"> · 🔒 내부 메모</span>}
                {e.kind === 'customer' && <span className="tag">고객</span>}
                {e.kind === 'public' && <span className="muted"> · 고객에게 답변</span>}</p>
              <p className="comment-text">{e.text}</p>
            </div>
          </li>
        ))}
        {entries.length === 0 && <li className="muted">표시할 활동이 없습니다.</li>}
      </ul>
    </section>
  )
}
