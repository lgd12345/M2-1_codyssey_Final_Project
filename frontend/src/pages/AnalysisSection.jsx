import React, { useState } from 'react'
import { analysisRunNotice, identifierCheckLine, isAnalysisRunning } from '../domain/workflow.js'
import { SourcePageButton } from './SourcePage.jsx'
import { MailCompose } from './MailCompose.jsx'
import { activitiesFor, firstSentences } from '../domain/analysis.js'

// 분석은 대화의 말풍선 하나로 나온다. 짧게: 요약, 원인 후보, 권장 활동(메일 초안 요청), 근거 접기.
// 현장 수리 절차는 서비스 부서의 업무이므로 이 화면에 두지 않는다.
// current=false 인 이전 분석에는 활동 버튼이 없다. 원본 페이지는 회차(revision)로 그 분석의 인용을 연다.
export function AnalysisBubble({ analysis: a, item, current, revision, dispatch, csrf, onChanged }) {
  const canAct = item.status !== '종결'  // a closed request offers no new actions
  const [open, setOpen] = useState(null)
  const [composing, setComposing] = useState(null)
  const [full, setFull] = useState(false)
  const summary = firstSentences(a.summary, 2)
  const cases = a.evidence.filter((e) => e.kind === 'fsr')
  const manuals = a.evidence.filter((e) => e.kind === 'manual')
  const activities = current && canAct && a.status === 'answered' ? activitiesFor(item.departments) : []
  const pageRevision = current ? undefined : revision  // the latest analysis is the server's default
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
                <div className="activity-row">
                  <span>{act.label}</span>
                  <button className="ghost small" aria-expanded={composing === act.key} disabled={!dispatch}
                    onClick={() => setComposing(composing === act.key ? null : act.key)}>{composing === act.key ? '접기' : '메일 작성'}</button>
                </div>
                {composing === act.key && <MailCompose item={item} departmentKey={act.key} csrf={csrf} onChanged={onChanged} onSent={() => setComposing(null)} />}
              </li>
            ))}
          </ol>
          <p className="muted small">‘메일 작성’을 누르면 작성란이 펼쳐집니다. 내용을 확인한 뒤 ‘보내기’를 누르면 발송됩니다.</p>
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
          <ul className="evidence">{manuals.map((e) => <EvidenceRow key={e.id} e={e} open={open} setOpen={setOpen} itemId={item.id} revision={pageRevision} />)}</ul>
        </details>
      )}
      <div className="ai-foot">
        <span className="ai-chip">✦ AI 생성</span>
      </div>
    </div>
  )
}

const sourceOf = (a, id) => a.evidence.find((e) => e.id === id)

function EvidenceRow({ e, open, setOpen, itemId, revision }) {
  const isOpen = open === e.id
  return (
    <li className={isOpen ? 'open' : ''}>
      <button className="evidence-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : e.id)}>
        <strong>{e.title}</strong><small>출처: {e.source}</small>
      </button>
      {isOpen && <div className="evidence-body"><pre>{e.excerpt}</pre><p className="note">적용 시 주의: {e.note}</p>
        {e.ref && itemId && <SourcePageButton itemId={itemId} evidenceId={e.id} title={e.title} revision={revision} />}</div>}
    </li>
  )
}


// 분석 결과가 아직 없을 때(진행 중, 실패, 시작 전)의 안내. 시작 버튼은 대화창의 `분석 시작` 칩이다.
export function PendingNotice({ item, error }) {
  const running = isAnalysisRunning(item)
  const notice = analysisRunNotice(item.analysisRun)
  return (
    <div className="analysis-pending">
      <p className="muted" role="status">{running ? '분석 중입니다. 매뉴얼과 과거 사례를 검색하고 있으며 완료되면 이 대화에 표시됩니다.' : '아직 분석 결과가 없습니다. ‘분석 시작’을 누르면 분석이 시작되고, 끝나면 질문할 수 있습니다.'}</p>
      {notice && <p className="error" role="alert">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  )
}
