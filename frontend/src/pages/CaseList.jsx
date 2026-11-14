import React, { useMemo, useState } from 'react'
import { caseHref } from '../navigation.js'
import { STATUSES, statusCounts } from '../domain/workflow.js'
import { CALL_REASONS } from '../domain/catalog.js'
import { Lozenge, formatDate } from '../ui.jsx'
import { NewCaseModal } from './NewCaseModal.jsx'

const unique = (items) => [...new Set(items)]

// Jira의 큐 사이드바(건수 포함)와 TRUMPF "My service cases"(기간·필터·결과 표)를 합친 목록.
export function CaseList({ cases, onCreate, equipment, modalOpen }) {
  const [queue, setQueue] = useState('전체')
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({ machine: '', creator: '', type: '', from: '', to: '' })
  const counts = statusCounts(cases)
  const set = (key) => (e) => setFilters({ ...filters, [key]: e.target.value })

  const machines = useMemo(() => unique(cases.map((c) => c.intake.machine)).sort(), [cases])
  const creators = useMemo(() => unique(cases.map((c) => c.intake.creator)).sort(), [cases])

  const shown = cases.filter((c) => {
    const day = formatDate(c.createdAt)
    const hay = `${c.id} ${c.title} ${c.intake.machine} ${c.intake.company}`.toLowerCase()
    return (queue === '전체' || c.status === queue)
      && (!search || hay.includes(search.toLowerCase()))
      && (!filters.machine || c.intake.machine === filters.machine)
      && (!filters.creator || c.intake.creator === filters.creator)
      && (!filters.type || c.intake.type === filters.type)
      && (!filters.from || day >= filters.from)
      && (!filters.to || day <= filters.to)
  })

  const active = [
    filters.machine && ['기계', filters.machine, 'machine'], filters.creator && ['접수자', filters.creator, 'creator'],
    filters.type && ['유형', filters.type, 'type'], filters.from && ['시작일', filters.from, 'from'], filters.to && ['종료일', filters.to, 'to'],
  ].filter(Boolean)

  return (
    <div className="queue-layout">
      <aside className="queue-side" aria-label="대기열">
        <h2>대기열</h2>
        <ul>
          {['전체', ...STATUSES].map((s) => (
            <li key={s}>
              <button className={queue === s ? 'queue-item active' : 'queue-item'} aria-current={queue === s ? 'true' : undefined} onClick={() => setQueue(s)}>
                <span>{s === '전체' ? '모든 요청' : s}</span><span className="count">{s === '전체' ? cases.length : counts[s]}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="queue-main" aria-labelledby="list-title">
        <div className="page-head row">
          <div><p className="page-eyebrow">CLAIM OPERATIONS</p><h1 id="list-title" className="page-title">서비스 요청</h1><p className="page-lead">접수된 요청을 분석하고 검토·승인해 부서로 전달합니다.</p></div>
          <a className="button primary" href="#/cases/new">새 요청</a>
        </div>

        <div className="filters">
          <input type="search" className="search" placeholder="요청 번호, 제목, 기계 검색" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="검색" />
          <label>시작일<input type="date" value={filters.from} onChange={set('from')} /></label>
          <label>종료일<input type="date" value={filters.to} onChange={set('to')} /></label>
          <label>기계<select value={filters.machine} onChange={set('machine')}><option value="">전체</option>{machines.map((m) => <option key={m}>{m}</option>)}</select></label>
          <label>접수자<select value={filters.creator} onChange={set('creator')}><option value="">전체</option>{creators.map((m) => <option key={m}>{m}</option>)}</select></label>
          <label>유형<select value={filters.type} onChange={set('type')}><option value="">전체</option>{CALL_REASONS.map((m) => <option key={m}>{m}</option>)}</select></label>
        </div>
        {active.length > 0 && (
          <div className="active-filters" aria-label="적용된 필터">
            <span className="muted small">적용된 필터</span>
            {active.map(([label, value, key]) => <button key={key} className="chip link" onClick={() => setFilters({ ...filters, [key]: '' })}>{label}: {value} ×</button>)}
            <button className="ghost small" onClick={() => setFilters({ machine: '', creator: '', type: '', from: '', to: '' })}>모두 지우기</button>
          </div>
        )}

        <div className="panel table-wrap">
          <table className="results">
            <thead><tr><th>요청 번호</th><th>요약</th><th>기계</th><th>유형</th><th>상태</th><th>접수자</th><th>접수일</th><th><span className="sr-only">상세</span></th></tr></thead>
            <tbody>
              {shown.length === 0 && <tr><td colSpan={8} className="empty">조건에 맞는 요청이 없습니다.</td></tr>}
              {shown.map((c) => (
                <tr key={c.id}>
                  <td><a href={caseHref(c.id)} className="key">{c.id}</a></td>
                  <td><a href={caseHref(c.id)} className="title-link">{c.title}</a></td>
                  <td>{c.intake.machine}</td>
                  <td>{c.intake.type}</td>
                  <td><Lozenge status={c.status} /></td>
                  <td>{c.intake.creator}</td>
                  <td>{formatDate(c.createdAt)}</td>
                  <td><a href={caseHref(c.id)} aria-label={`${c.id} 상세 보기`} className="arrow">›</a></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="table-foot muted small">총 {shown.length}건</p>
        </div>
      </section>

      {modalOpen && <NewCaseModal onCreate={onCreate} equipment={equipment} />}
    </div>
  )
}
