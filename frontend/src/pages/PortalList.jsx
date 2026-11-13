import React, { useMemo, useState } from 'react'
import { portalHref } from '../navigation.js'
import { customerStatus } from '../mock/store.js'
import { CALL_REASONS } from '../mock/meta.js'
import { formatDate } from '../ui.jsx'
import { NewCaseModal } from './NewCaseModal.jsx'

const unique = (items) => [...new Set(items)]
const TONE = { 접수됨: 'neutral', '확인 중': 'blue', '정보 요청': 'yellow', '처리 중': 'blue', 완료: 'green' }
const COLUMNS = [
  ['machine', '기계'], ['status', '상태'], ['type', '유형'], ['id', '요청 번호'], ['creator', '접수자'], ['createdAt', '접수일'],
]

// TRUMPF "My service cases": 안내문, 새 요청 버튼, 기간(From/To), 상태·기계·접수자·유형 필터, 적용된 필터,
// 결과 표(열 제목으로 정렬, 행 오른쪽 화살표로 상세). 고객에게는 내부 상태 대신 진행 단계만 보여 준다.
export function PortalList({ cases, company, dispatch, modalOpen, nextId }) {
  const [filters, setFilters] = useState({ status: '', machine: '', creator: '', type: '', from: '', to: '' })
  const [sort, setSort] = useState({ key: 'createdAt', dir: 'desc' })
  const set = (key) => (e) => setFilters({ ...filters, [key]: e.target.value })

  const rows = useMemo(() => cases.map((c) => ({
    c, machine: c.intake.machine, status: customerStatus(c), type: c.intake.type, id: c.id, creator: c.intake.creator, createdAt: c.createdAt,
  })), [cases])

  const shown = rows
    .filter((r) => (!filters.status || r.status === filters.status) && (!filters.machine || r.machine === filters.machine)
      && (!filters.creator || r.creator === filters.creator) && (!filters.type || r.type === filters.type)
      && (!filters.from || formatDate(r.createdAt) >= filters.from) && (!filters.to || formatDate(r.createdAt) <= filters.to))
    .sort((a, b) => (a[sort.key] < b[sort.key] ? -1 : a[sort.key] > b[sort.key] ? 1 : 0) * (sort.dir === 'asc' ? 1 : -1))

  const active = [['상태', filters.status, 'status'], ['기계', filters.machine, 'machine'], ['접수자', filters.creator, 'creator'], ['유형', filters.type, 'type'], ['시작일', filters.from, 'from'], ['종료일', filters.to, 'to']].filter((a) => a[1])
  const toggleSort = (key) => setSort({ key, dir: sort.key === key && sort.dir === 'asc' ? 'desc' : 'asc' })

  return (
    <section className="portal" aria-labelledby="portal-title">
      <div className="portal-hero">
        <h1 id="portal-title">내 서비스 요청</h1>
        <p className="muted">{company}의 서비스 요청을 한곳에서 확인합니다. 접수한 요청은 담당 서비스 엔지니어에게 바로 전달되고, 진행 상황은 이 화면에서 확인할 수 있습니다. 회사의 모든 직원이 같은 요청을 볼 수 있습니다.</p>
        <a className="button create-case" href="#/portal/new">새 서비스 요청</a>
      </div>

      <div className="filters">
        <label>시작일<input type="date" value={filters.from} onChange={set('from')} /></label>
        <label>종료일<input type="date" value={filters.to} onChange={set('to')} /></label>
        <label>상태<select value={filters.status} onChange={set('status')}><option value="">전체</option>{Object.keys(TONE).map((s) => <option key={s}>{s}</option>)}</select></label>
        <label>기계<select value={filters.machine} onChange={set('machine')}><option value="">전체</option>{unique(cases.map((c) => c.intake.machine)).sort().map((m) => <option key={m}>{m}</option>)}</select></label>
        <label>접수자<select value={filters.creator} onChange={set('creator')}><option value="">전체</option>{unique(cases.map((c) => c.intake.creator)).sort().map((m) => <option key={m}>{m}</option>)}</select></label>
        <label>유형<select value={filters.type} onChange={set('type')}><option value="">전체</option>{CALL_REASONS.map((m) => <option key={m}>{m}</option>)}</select></label>
      </div>
      {active.length > 0 && (
        <div className="active-filters" aria-label="적용된 필터">
          <span className="muted small">적용된 필터</span>
          {active.map(([label, value, key]) => <button key={key} className="chip link" onClick={() => setFilters({ ...filters, [key]: '' })}>{label}: {value} ×</button>)}
        </div>
      )}

      <h2 className="results-title">결과</h2>
      <div className="panel table-wrap">
        <table className="results">
          <thead><tr>
            {COLUMNS.map(([key, label]) => <th key={key} aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}><button className="th-sort" onClick={() => toggleSort(key)}>{label}{sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}</button></th>)}
            <th><span className="sr-only">상세</span></th>
          </tr></thead>
          <tbody>
            {shown.length === 0 && <tr><td colSpan={7} className="empty">조건에 맞는 서비스 요청이 없습니다.</td></tr>}
            {shown.map((r) => (
              <tr key={r.id}>
                <td>{r.machine}<small>{r.c.intake.serial}</small></td>
                <td><span className={`lozenge lozenge-${TONE[r.status]}`}>{r.status}</span></td>
                <td>{r.type}</td>
                <td><a className="key" href={portalHref(r.id)}>{r.id}</a><small>{r.c.title}</small></td>
                <td>{r.creator}</td>
                <td>{formatDate(r.createdAt)}</td>
                <td><a href={portalHref(r.id)} className="arrow" aria-label={`${r.id} 상세 보기`}>›</a></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="table-foot muted small">총 {shown.length}건</p>
      </div>

      {modalOpen && <NewCaseModal dispatch={dispatch} nextId={nextId} portal company={company} />}
    </section>
  )
}
