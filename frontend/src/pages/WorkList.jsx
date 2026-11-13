import React, { useState } from 'react'
import { WORK_STATUSES, workItems } from '../domain/workflow.js'
import { DEPARTMENTS } from '../domain/catalog.js'
import { Avatar, formatDate } from '../ui.jsx'
import { workHref } from '../navigation.js'

const TONE = { 전달됨: 'blue', '진행 중': 'yellow', 완료: 'green' }

// Jira의 연결 업무를 받은 팀의 큐. 승인된 요청에서 생성된 업무만 들어오며, 사이드바에 상태별 건수를 보여 준다.
export function WorkList({ cases, deptKey, onDeptChange }) {
  const [queue, setQueue] = useState('전체')
  const deptName = DEPARTMENTS.find((d) => d.key === deptKey)?.name
  const all = workItems(cases, deptKey).sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
  const shown = queue === '전체' ? all : all.filter((w) => w.status === queue)

  return (
    <div className="queue-layout">
      <aside className="queue-side" aria-label="업무 큐">
        <label className="team-select">팀
          <select value={deptKey} onChange={(e) => { onDeptChange(e.target.value); setQueue('전체') }}>
            {DEPARTMENTS.map((d) => <option key={d.key} value={d.key}>{d.name}팀</option>)}
          </select>
        </label>
        <h2>업무 큐</h2>
        <ul>
          {['전체', ...WORK_STATUSES].map((s) => (
            <li key={s}>
              <button className={queue === s ? 'queue-item active' : 'queue-item'} aria-current={queue === s ? 'true' : undefined} onClick={() => setQueue(s)}>
                <span>{s === '전체' ? '모든 업무' : s}</span><span className="count">{s === '전체' ? all.length : all.filter((w) => w.status === s).length}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="queue-main" aria-labelledby="work-title">
        <div className="page-head">
          <p className="page-eyebrow">TEAM INBOX</p>
          <h1 id="work-title" className="page-title">{deptName}팀 받은 업무</h1>
          <p className="page-lead">품질 담당자가 승인한 요청에서 {deptName}팀으로 전달된 업무입니다. 처리 결과를 입력하면 원본 요청에 반영됩니다.</p>
        </div>
        <div className="panel table-wrap">
          <table className="results">
            <thead><tr><th>업무 번호</th><th>요약</th><th>고객사 · 기계</th><th>상태</th><th>담당자</th><th>받은 날</th><th><span className="sr-only">상세</span></th></tr></thead>
            <tbody>
              {shown.length === 0 && <tr><td colSpan={7} className="empty">받은 업무가 없습니다.</td></tr>}
              {shown.map((w) => (
                <tr key={w.workKey}>
                  <td><a className="key" href={workHref(w.workKey)}>{w.workKey}</a></td>
                  <td><a className="title-link" href={workHref(w.workKey)}>{w.caseTitle}</a><small>원본 {w.caseId}</small></td>
                  <td>{w.intake.company}<small>{w.intake.machine} · {w.intake.serial}</small></td>
                  <td><span className={`lozenge lozenge-${TONE[w.status]}`}>{w.status}</span></td>
                  <td>{w.assignee ? <span className="who"><Avatar name={w.assignee} /> {w.assignee}</span> : <span className="muted">미지정</span>}</td>
                  <td>{formatDate(w.createdAt)}</td>
                  <td><a className="arrow" href={workHref(w.workKey)} aria-label={`${w.workKey} 상세 보기`}>›</a></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="table-foot muted small">총 {shown.length}건</p>
        </div>
      </section>
    </div>
  )
}
