import React, { useState } from 'react'
import { analysisRunNotice, canStartAnalysis, isAnalysisRunning } from '../domain/workflow.js'

// 위치는 Jira의 "Agent sessions"(Uses AI. Verify results.), 내용 구성은 Siemens Maintenance Copilot의
// 4개 메뉴(Troubleshooting steps / Check maintenance history / Find recommended spare parts / Access repair manual)를 따른다.
const TABS = [
  { key: 'steps', label: '문제 해결 단계' },
  { key: 'history', label: '과거 정비 이력' },
  { key: 'parts', label: '권장 부품' },
  { key: 'manual', label: '매뉴얼 열람' },
]

export function AnalysisSection({ item, dispatch, me, onAnalyze, analyzing, error }) {
  const [tab, setTab] = useState('steps')
  const [open, setOpen] = useState(null)
  const a = item.analysis
  return (
    <section className="block" aria-labelledby="ai-title">
      <div className="block-head">
        <h2 id="ai-title"><span className="spark" aria-hidden="true">✦</span> AI 분석</h2>
        <span className="muted small">ⓘ AI를 사용합니다. 결과를 확인해 주세요.</span>
      </div>
      <div className="ai-box">
        <div className="quick" role="tablist" aria-label="AI 분석 메뉴">
          {TABS.map(t => <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? 'quick-btn active' : 'quick-btn'} onClick={() => setTab(t.key)}>{t.label}</button>)}
        </div>
        {!a ? <Pending item={item} onAnalyze={onAnalyze} analyzing={analyzing} error={error} /> : <>
          {a.status === 'insufficient_evidence' && <p className="notice warn" role="note">관련 근거가 부족해 원인 후보와 권장 사항을 제시하지 않았습니다.</p>}
          {a.caseSearch === 'unavailable' && <p className="notice warn" role="note">과거 사례 검색 결과를 확인하지 못했습니다.</p>}
          <p className="summary-text">{a.summary}</p>
          <div className="ai-answer" role="tabpanel">
            {tab === 'steps' && <Steps a={a} />}
            {tab === 'history' && <History a={a} open={open} setOpen={setOpen} />}
            {tab === 'parts' && <Parts a={a} />}
            {tab === 'manual' && <Manual a={a} open={open} setOpen={setOpen} />}
          </div>
          <div className="ai-foot">
            <span className="ai-chip">✦ AI 생성</span>
            <button className="ghost small" disabled={!dispatch} onClick={() => dispatch({ type: 'ADD_COMMENT', id: item.id, kind: 'internal', text: a.summary })}>내부 메모로 복사</button>
            <button className="ghost small" disabled title="평가 저장 기능 미연결" aria-label="도움이 됨">👍</button>
            <button className="ghost small" disabled title="평가 저장 기능 미연결" aria-label="도움이 안 됨">👎</button>
          </div>
        </>}
      </div>
    </section>
  )
}

const sourceOf = (a, id) => a.evidence.find((e) => e.id === id)

function Steps({ a }) {
  return (
    <>
      <h3>추정 원인</h3>
      {a.causes.length === 0 ? <p className="muted">근거가 부족해 원인 후보를 제시하지 않았습니다.</p> : (
        <ol className="causes">
          {a.causes.map((c) => (
            <li key={c.title}>
              <div className="cause-head"><strong>{c.title}</strong><span className={`lozenge level-${c.level}`}>가능성 {c.level}</span></div>
              <p>{c.detail}</p>
              <p className="source">출처: {c.evidence.map((id) => sourceOf(a, id).source).join(' · ')}</p>
            </li>
          ))}
        </ol>
      )}
      <h3>점검 순서</h3>
      <ol className="steps-list">{a.steps.map((s) => <li key={s}>{s}</li>)}</ol>
      {a.questions.length > 0 && (<><h3>추가 확인이 필요한 사항</h3><ul className="questions">{a.questions.map((q) => <li key={q}>{q}</li>)}</ul></>)}
    </>
  )
}

function History({ a, open, setOpen }) {
  if (a.caseSearch === 'unavailable') return <p className="muted">과거 사례 검색이 연결되지 않아 이력을 확인하지 못했습니다. 이 항목은 연결 후에 제공됩니다.</p>
  const cases = a.evidence.filter((e) => e.kind === 'fsr')
  if (cases.length === 0) return <p className="muted">유사한 과거 사례가 없습니다.</p>
  return (
    <>
      <h3>유사 과거 사례 {cases.length}건</h3>
      <ul className="evidence">{cases.map((e) => <EvidenceRow key={e.id} e={e} open={open} setOpen={setOpen} />)}</ul>
      <p className="muted small">과거 사례는 참고용입니다. 현재 건의 원인이나 보증·귀책을 확정하지 않습니다.</p>
    </>
  )
}

function Parts({ a }) {
  if (a.parts.length === 0) return <p className="muted">매뉴얼과 과거 사례에서 명시적으로 권장된 부품이 없습니다.</p>
  return (
    <>
      <h3>권장 부품</h3>
      <ul className="parts">{a.parts.map((p) => <li key={p.name}><strong>{p.name}</strong><p>{p.note}</p><p className="source">출처: {p.source}</p></li>)}</ul>
    </>
  )
}

function Manual({ a, open, setOpen }) {
  const manuals = a.evidence.filter((e) => e.kind === 'manual')
  return (
    <>
      <h3>관련 매뉴얼 {manuals.length}건</h3>
      <ul className="evidence">{manuals.map((e) => <EvidenceRow key={e.id} e={e} open={open} setOpen={setOpen} />)}</ul>
    </>
  )
}

function EvidenceRow({ e, open, setOpen }) {
  const isOpen = open === e.id
  return (
    <li className={isOpen ? 'open' : ''}>
      <button className="evidence-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : e.id)}>
        <strong>{e.title}</strong><small>출처: {e.source}</small>
      </button>
      {isOpen && <div className="evidence-body"><pre>{e.excerpt}</pre><p className="note">적용 시 주의: {e.note}</p></div>}
    </li>
  )
}

function Pending({ item, onAnalyze, analyzing, error }) {
  const running = isAnalysisRunning(item)
  const notice = analysisRunNotice(item.analysisRun)
  return (
    <div className="analysis-pending">
      <p className="muted" role="status">{running ? '분석 중입니다. 매뉴얼과 과거 사례를 검색하고 있으며 완료되면 이 화면에 표시됩니다.' : '아직 분석 결과가 없습니다.'}</p>
      {notice && <p className="error" role="alert">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {canStartAnalysis(item) && onAnalyze && (
        <button className="primary" disabled={analyzing} onClick={() => onAnalyze(item.id)}>{analyzing ? '분석 요청 중…' : item.analysisRun?.status === 'failed' ? '분석 다시 시도' : 'AI 분석 시작'}</button>
      )}
    </div>
  )
}
