import React, { useState } from 'react'
import { analysisRunNotice, canStartAnalysis, canAddInfo, identifierCheckLine, isAnalysisRunning } from '../domain/workflow.js'
import { SourcePageButton } from './SourcePage.jsx'
import { formatTime } from '../ui.jsx'
import { CHAT_ASK_EVENT, activitiesFor, activityQuestion, firstSentences } from '../domain/analysis.js'

// 분석은 대화의 말풍선 하나로 나온다. 짧게: 요약, 원인 후보, 권장 활동(메일 초안 요청), 근거 접기.
// 현장 수리 절차는 서비스 부서의 업무이므로 이 화면에 두지 않는다.
// current=false 인 이전 분석은 활동 버튼과 원본 페이지 열기가 없다(원본 페이지는 서버가 항상 최신 분석의 인용만 연다).
export function AnalysisBubble({ analysis: a, item, current, revision, dispatch }) {
  const [open, setOpen] = useState(null)
  const [full, setFull] = useState(false)
  const summary = firstSentences(a.summary, 2)
  const cases = a.evidence.filter((e) => e.kind === 'fsr')
  const manuals = a.evidence.filter((e) => e.kind === 'manual')
  const activities = current && a.status === 'answered' ? activitiesFor(item.departments) : []
  const itemId = current ? item.id : undefined
  return (
    <div className="analysis-bubble">
      {revision > 1 && <p className="muted small">분석 {revision}회차</p>}
      {a.status === 'insufficient_evidence' && <p className="notice warn" role="note">관련 근거가 부족해 원인 후보와 권장 사항을 제시하지 않았습니다.</p>}
      {a.caseSearch === 'unavailable' && <p className="notice warn" role="note">과거 사례 검색 결과를 확인하지 못했습니다.</p>}
      <p className="summary-text">{full ? a.summary : summary.text}
        {summary.cut && <> <button className="linkish" onClick={() => setFull(!full)}>{full ? '접기' : '더 보기'}</button></>}</p>
      {a.identifierChecks?.length > 0 && (
        <ul className="identifier-checks" aria-label="식별자 확인">
          {a.identifierChecks.map((check) => <li key={`${check.kind}:${check.value}`} className={check.status}>{identifierCheckLine(check)}</li>)}
        </ul>
      )}
      {a.causes.length > 0 && (
        <>
          <h3>원인 후보</h3>
          <ol className="causes">
            {a.causes.map((c) => (
              <li key={c.title}>
                <div className="cause-head"><strong>{c.title}</strong><span className={`lozenge level-${c.level}`}>가능성 {c.level}</span></div>
                <p className="source">출처: {c.evidence.map((id) => sourceOf(a, id).source).join(' · ')}</p>
                <details><summary>자세히</summary><p>{c.detail}</p></details>
              </li>
            ))}
          </ol>
        </>
      )}
      {activities.length > 0 && (
        <>
          <h3>권장 활동 {activities.length}건</h3>
          <ol className="activities" aria-label="권장 활동">
            {activities.map((act) => (
              <li key={act.key}>
                <span>{act.label}</span>
                <button className="ghost small" disabled={!dispatch} onClick={() => window.dispatchEvent(new CustomEvent(CHAT_ASK_EVENT, { detail: activityQuestion(act) }))}>메일 작성</button>
              </li>
            ))}
          </ol>
          <p className="muted small">메일은 초안만 만들어지며, 내용을 확인하고 보내기를 눌러야 발송됩니다.</p>
        </>
      )}
      {a.status === 'insufficient_evidence' && a.questions.length > 0 && (
        <><h3>운영진이 확인할 사항</h3><ul className="questions">{a.questions.map((q) => <li key={q}>{q}</li>)}</ul></>
      )}
      {a.caseSearch !== 'unavailable' && cases.length > 0 && (
        <details className="evidence-fold"><summary>과거 사례 {cases.length}건 (보기)</summary>
          <ul className="evidence">{cases.map((e) => <EvidenceRow key={e.id} e={e} open={open} setOpen={setOpen} />)}</ul>
          <p className="muted small">과거 사례는 참고용입니다. 현재 건의 원인이나 보증·귀책을 확정하지 않습니다.</p>
        </details>
      )}
      {manuals.length > 0 && (
        <details className="evidence-fold"><summary>관련 문서 {manuals.length}건 (보기)</summary>
          <ul className="evidence">{manuals.map((e) => <EvidenceRow key={e.id} e={e} open={open} setOpen={setOpen} itemId={itemId} />)}</ul>
        </details>
      )}
      <div className="ai-foot">
        <span className="ai-chip">✦ AI 생성</span>
        {current && <button className="ghost small" disabled={!dispatch} onClick={() => dispatch({ type: 'ADD_COMMENT', id: item.id, kind: 'internal', text: a.summary })}>내부 메모로 복사</button>}
      </div>
    </div>
  )
}

// What the operator learned by phone or on site. It is not shown to customers and feeds the next analysis.
export function AdditionalInfo({ item, dispatch }) {
  const [text, setText] = useState('')
  const notes = item.additionalInfo ?? []
  const can = Boolean(dispatch) && canAddInfo(item)
  if (!can && notes.length === 0) return null
  return (
    <div className="additional-info">
      <h3>추가 정보</h3>
      {notes.length > 0 && (
        <ul className="info-notes" aria-label="운영진이 입력한 추가 정보">
          {notes.map((note) => <li key={note.id}><span className="muted small">{note.by} · {formatTime(note.at)}</span><p>{note.text}</p></li>)}
        </ul>
      )}
      {can && (
        <>
          <p className="muted small">전화·현장 확인 등 앱 밖에서 알게 된 내용을 입력하면 다음 재분석에 반영됩니다. 고객에게는 표시되지 않습니다.</p>
          <textarea rows={3} maxLength={2000} value={text} aria-label="추가 정보 입력" onChange={(e) => setText(e.target.value)} />
          <div className="actions">
            <button className="primary" disabled={!text.trim()} onClick={() => { dispatch({ type: 'ADD_INFO', id: item.id, text }); setText('') }}>추가 정보 저장</button>
          </div>
        </>
      )}
    </div>
  )
}

const sourceOf = (a, id) => a.evidence.find((e) => e.id === id)

function EvidenceRow({ e, open, setOpen, itemId }) {
  const isOpen = open === e.id
  return (
    <li className={isOpen ? 'open' : ''}>
      <button className="evidence-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : e.id)}>
        <strong>{e.title}</strong><small>출처: {e.source}</small>
      </button>
      {isOpen && <div className="evidence-body"><pre>{e.excerpt}</pre><p className="note">적용 시 주의: {e.note}</p>
        {e.ref && itemId && <SourcePageButton itemId={itemId} evidenceId={e.id} title={e.title} />}</div>}
    </li>
  )
}


// 분석 결과가 아직 없을 때(진행 중, 실패, 시작 전)의 안내. 시작 버튼은 대화창의 `분석해줘` 칩이다.
export function PendingNotice({ item, error }) {
  const running = isAnalysisRunning(item)
  const notice = analysisRunNotice(item.analysisRun)
  return (
    <div className="analysis-pending">
      <p className="muted" role="status">{running ? '분석 중입니다. 매뉴얼과 과거 사례를 검색하고 있으며 완료되면 이 대화에 표시됩니다.' : '아직 분석 결과가 없습니다. 아래 `분석해줘` 버튼을 눌러 시작하세요.'}</p>
      {notice && <p className="error" role="alert">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  )
}
