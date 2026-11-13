import React, { useState } from 'react'
import { workItems } from '../domain/workflow.js'
import { Avatar, Lozenge, formatDate, formatTime } from '../ui.jsx'

const TONE = { 전달됨: 'blue', '진행 중': 'yellow', 완료: 'green' }

// 연결 업무를 받은 팀이 보는 화면(Jira linked work item). 승인된 지시 내용과 원본 요청을 읽고,
// 처리를 시작해 결과를 입력하면 원본 요청에서 이 업무가 완료로 보인다.
export function WorkDetail({ cases, workKey, deptKey, dispatch }) {
  const [summary, setSummary] = useState('')
  const [hours, setHours] = useState('')
  const w = workItems(cases, deptKey).find((x) => x.workKey === workKey)
  if (!w) return <section className="center-card"><h1>업무를 찾을 수 없습니다</h1><p className="muted">이 팀에 전달된 업무가 아닙니다.</p><a href="#/work">받은 업무로</a></section>

  const parent = cases.find((c) => c.id === w.caseId)
  const siblings = parent.linked.filter((l) => l.workKey !== workKey)
  const events = parent.history.filter((h) => h.text.includes(workKey) || h.text.includes('승인 ·'))
  const start = () => dispatch({ type: 'WORK_START', id: w.caseId, workKey })
  const complete = () => dispatch({ type: 'WORK_COMPLETE', id: w.caseId, workKey, result: { summary, hours } })
  const asset = parent.intake.asset

  return (
    <article className="issue" aria-labelledby="wd-title">
      <div className="crumbs"><a href="#/work">← 뒤로</a><span className="key">{workKey}</span><span className="muted small">원본 요청 {w.caseId}</span></div>
      <div className="issue-grid">
        <div className="issue-main">
          <h1 id="wd-title">{w.caseTitle}</h1>

          <section className="block"><div className="block-head"><h2>지시 내용</h2><span className="tag">품질 담당자 승인 완료</span></div>
            <pre>{w.content}</pre>
            {w.edited && <p className="muted small">검토 중 담당자가 수정한 내용입니다.</p>}
          </section>

          <section className="block"><div className="block-head"><h2>원본 요청</h2></div>
            <div className="request-card">
              <dl className="qa">
                <div><dt>고객사 · 기계</dt><dd>{parent.intake.company} · {parent.intake.machine} · {parent.intake.serial}</dd></div>
                <div><dt>접수 내용</dt><dd className="pre">{parent.intake.symptom}</dd></div>
                <div><dt>알람 · 오류 번호</dt><dd>{parent.intake.alarm || '없음'}</dd></div>
                {asset && <div><dt>보증</dt><dd>{asset.warranty} ({asset.warrantyNote}) · 설치 {asset.installDate} · 이전 서비스 {asset.previous}건</dd></div>}
              </dl>
            </div>
          </section>

          {parent.analysis && (
            <section className="block"><div className="block-head"><h2>AI 분석 요약</h2><span className="muted small">참고용 · 근거 {parent.analysis.evidence.length}건</span></div>
              <p>{parent.analysis.summary}</p>
              {parent.analysis.steps.length > 0 && <><h3>점검 순서</h3><ol className="steps-list">{parent.analysis.steps.map((s) => <li key={s}>{s}</li>)}</ol></>}
            </section>
          )}

          <section className="block"><div className="block-head"><h2>처리 결과</h2></div>
            {w.status === '완료' ? (
              <div className="request-card"><p>{w.result.summary}</p><p className="muted small">작업 시간 {w.result.hours ? `${w.result.hours}시간` : '미입력'} · {w.assignee} · {formatTime(w.doneAt)} 완료</p></div>
            ) : w.status === '진행 중' ? (
              <div>
                <label>조치 내용 *<textarea rows={5} value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="무엇을 확인하고 어떻게 조치했는지 적어 주세요." /></label>
                <label className="narrow-field">작업 시간(시간)<input value={hours} onChange={(e) => setHours(e.target.value)} inputMode="decimal" /></label>
                <button className="primary" disabled={!dispatch || !summary.trim()} onClick={complete}>처리 완료</button>
              </div>
            ) : <p className="muted">처리를 시작하면 결과를 입력할 수 있습니다.</p>}
          </section>

          <section className="block"><div className="block-head"><h2>이력</h2></div>
            <ul className="activity">{events.map((e, i) => <li key={i} className="event"><time>{formatTime(e.at)}</time> {e.text}</li>)}</ul>
          </section>
        </div>

        <aside className="issue-side" aria-label="상태와 세부 정보">
          <div className="status-menu">
            <span className={`status-btn status-${TONE[w.status] === 'green' ? 'green' : TONE[w.status] === 'yellow' ? 'yellow' : 'blue'}`}>{w.status}</span>
          </div>
          {w.status === '전달됨' && <div className="side-panel approval"><h3>처리를 시작하세요</h3><p className="small">지시 내용을 확인한 뒤 처리를 시작하면 담당자로 지정됩니다.</p><button className="primary" disabled={!dispatch} onClick={start}>처리 시작</button></div>}
          <div className="side-panel details">
            <h3>세부 정보</h3>
            <dl className="detail-list">
              <div><dt>담당자</dt><dd>{w.assignee ? <><Avatar name={w.assignee} /> {w.assignee}</> : <>
                <span className="muted">미지정</span> <button className="linkish" disabled={!dispatch} onClick={() => dispatch({ type: 'WORK_ASSIGN', id: w.caseId, workKey })}>나에게 지정</button></>}</dd></div>
              <div><dt>원본 상태</dt><dd><Lozenge status={parent.status} /></dd></div>
              <div><dt>받은 날</dt><dd>{formatDate(w.createdAt)}</dd></div>
              <div><dt>진행 시작</dt><dd>{w.startedAt ? formatTime(w.startedAt) : '-'}</dd></div>
              <div><dt>완료</dt><dd>{w.doneAt ? formatTime(w.doneAt) : '-'}</dd></div>
            </dl>
          </div>
          <div className="side-panel">
            <h3>같은 요청의 다른 업무</h3>
            {siblings.length === 0 ? <p className="muted small">다른 팀으로 전달된 업무가 없습니다.</p> : (
              <ul className="siblings">{siblings.map((s) => <li key={s.workKey}><span className="key">{s.workKey}</span> {s.name}팀 <span className={`lozenge lozenge-${TONE[s.status]}`}>{s.status}</span></li>)}</ul>
            )}
          </div>
        </aside>
      </div>
    </article>
  )
}
