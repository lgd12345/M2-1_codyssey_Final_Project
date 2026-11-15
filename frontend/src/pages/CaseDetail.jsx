import React, { useState } from 'react'
import { canResolve, chatReady, isAnalysisRunning, mailLines } from '../domain/workflow.js'
import { Avatar, formatTime } from '../ui.jsx'
import { AdditionalInfo } from './AnalysisSection.jsx'
import { Activity } from './Activity.jsx'
import { ChatPanel } from './ChatPanel.jsx'

// 요청 상세: 왼쪽에 요청 정보·AI 분석·대화·활동, 오른쪽에 상태와 종결·세부 정보 패널. 분석 전에는 분석 시작만 보이고, 분석 후에 나머지가 나타난다.
export function CaseDetail({ item, dispatch, me, onAnalyze, analyzing, analysisError, csrf, onChanged }) {
  if (!item) return <section className="center-card"><h1>요청을 찾을 수 없습니다</h1><a href="#/cases">대기열로</a></section>
  return (
    <article className="issue" aria-labelledby="detail-title">
      <div className="crumbs"><a href="#/cases">← 뒤로</a><span className="key">{item.id}</span></div>
      <div className="issue-grid">
        <div className="issue-main">
          <h1 id="detail-title">{item.title}</h1>
          <RequestCard item={item} />
          {csrf && <ChatPanel item={item} csrf={csrf} onChanged={onChanged} dispatch={dispatch} onAnalyze={onAnalyze} analyzing={analyzing} analysisError={analysisError} />}
          {chatReady(item) && <AdditionalInfo item={item} />}
          <Activity item={item} />
        </div>
        <aside className="issue-side" aria-label="상태와 세부 정보">
          <StatusBadge item={item} />
          <ResolvePanel item={item} dispatch={dispatch} />
          <DetailsPanel item={item} />
        </aside>
      </div>
    </article>
  )
}

function RequestCard({ item }) {
  const [hidden, setHidden] = useState(false)
  const { intake } = item
  return (
    <div className="request-card">
      <div className="request-head">
        <Avatar name={intake.creator} />
        <p><strong>{intake.creator}</strong>님이 포털로 접수했습니다<br /><small>{formatTime(item.createdAt)}</small></p>
        <button className="linkish" onClick={() => setHidden(!hidden)} aria-expanded={!hidden}>{hidden ? '세부 정보 보기' : '세부 정보 숨기기'}</button>
      </div>
      {!hidden && (
        <dl className="qa">
          <div><dt>접수 사유</dt><dd>{intake.type}</dd></div>
          <div><dt>기종</dt><dd>{intake.company} · {intake.machine}</dd></div>
          <div><dt>메시지</dt><dd className="pre">{intake.symptom}</dd></div>
        </dl>
      )}
    </div>
  )
}

function StatusBadge({ item }) {
  return <div className="status-menu"><span className={`status-btn status-${item.status === '종결' ? 'green' : 'blue'}`} role="status" aria-label={`상태 ${item.status}`}>{item.status}</span></div>
}

// 처리 결과는 고객 포털과 완료 메일에 전달된다. 종결은 운영진이 직접 한다.
function ResolvePanel({ item, dispatch }) {
  const [note, setNote] = useState('')
  if (item.status === '종결') {
    return <div className="side-panel resolved"><h3>종결됨</h3><p><strong>{item.resolution.by}</strong> · {formatTime(item.resolution.at)}</p><p className="small pre">{item.resolution.note}</p><p className="muted small">고객 포털에서 완료로 표시되고, 처리 결과가 보입니다.</p></div>
  }
  if (isAnalysisRunning(item)) return <div className="side-panel"><h3>분석 중</h3><p className="muted small">분석이 끝나면 처리 결과를 적어 종결할 수 있습니다.</p></div>
  if (!canResolve(item)) return <div className="side-panel"><h3>처리 대기</h3><p className="muted small">‘분석 시작’을 선택하면 처리 중이 되고, 그 뒤에 처리 결과를 적어 종결할 수 있습니다.</p></div>
  return (
    <div className="side-panel resolution">
      <h3>처리 결과 · 종결</h3>
      <p className="small">처리 결과는 고객 포털과 완료 메일로 전달됩니다.</p>
      <label className="small">처리 결과 (고객에게 보입니다)<textarea rows={4} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} /></label>
      <button className="primary" disabled={!dispatch || !note.trim()} onClick={() => dispatch({ type: 'RESOLVE', id: item.id, note: note.trim() })}>요청 종결</button>
    </div>
  )
}

function DetailsPanel({ item }) {
  const { intake, analysis } = item
  const manual = analysis?.evidence.filter((e) => e.kind === 'manual').length ?? 0
  const cases = analysis?.evidence.filter((e) => e.kind === 'fsr').length ?? 0
  return (
    <div className="side-panel details">
      <h3>세부 정보</h3>
      <dl className="detail-list">
        <div><dt>접수자</dt><dd><Avatar name={intake.creator} /> {intake.creator}</dd></div>
        <div><dt>접수 사유</dt><dd>{intake.type}</dd></div>
        <div><dt>고객사</dt><dd>{intake.company}</dd></div>
        <div><dt>기종</dt><dd>{intake.machine}</dd></div>
        <div><dt>지식 근거</dt><dd>{analysis ? `${manual + cases}건 (매뉴얼 ${manual}, 과거 사례 ${cases})` : '미분석'}</dd></div>
        {mailLines(item.mail).length > 0 && <div><dt>알림 메일</dt><dd><ul className="mail-lines">{mailLines(item.mail).map((line) => <li key={line}>{line}</li>)}</ul></dd></div>}
      </dl>
      <p className="muted small">생성 {formatTime(item.createdAt)}{item.revision > 1 ? ` · 재분석 ${item.revision - 1}회` : ''}</p>
    </div>
  )
}
