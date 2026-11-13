import React, { useState } from 'react'
import { canApprove, canReanalyze, canResolve, isEditable } from '../domain/workflow.js'
import { Avatar, formatTime } from '../ui.jsx'
import { AnalysisSection } from './AnalysisSection.jsx'
import { DeptSection } from './DeptSection.jsx'
import { Activity } from './Activity.jsx'

// Jira 요청 상세(work item view): 왼쪽에 요청 정보·AI·연결 업무·활동, 오른쪽에 상태 버튼과 승인·세부 정보 패널.
export function CaseDetail({ item, dispatch, me, onAnalyze, analyzing, analysisError }) {
  if (!item) return <section className="center-card"><h1>요청을 찾을 수 없습니다</h1><a href="#/cases">대기열로</a></section>
  return (
    <article className="issue" aria-labelledby="detail-title">
      <div className="crumbs"><a href="#/cases">← 뒤로</a><span className="key">{item.id}</span></div>
      <div className="issue-grid">
        <div className="issue-main">
          <h1 id="detail-title">{item.title}</h1>
          {item.closeRequested && item.status !== '종결' && <p className="notice warn" role="status"><strong>고객이 종결을 요청했습니다.</strong> 활동의 고객 메시지를 확인하세요.</p>}
          <RequestCard item={item} />
          <AnalysisSection item={item} dispatch={dispatch} me={me} onAnalyze={onAnalyze} analyzing={analyzing} error={analysisError} />
          <DeptSection item={item} dispatch={dispatch} />
          <Activity item={item} dispatch={dispatch} me={me} />
        </div>
        <aside className="issue-side" aria-label="상태와 세부 정보">
          <StatusMenu item={item} dispatch={dispatch} />
          <ApprovalPanel item={item} dispatch={dispatch} me={me} />
          <DetailsPanel item={item} dispatch={dispatch} me={me} />
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
          <div><dt>기계 · 호기</dt><dd>{intake.company} · {intake.machine} · {intake.serial}</dd></div>
          <div><dt>알람 · 오류 번호</dt><dd>{intake.alarm || '없음'}</dd></div>
          <div><dt>발생 상황</dt><dd>{intake.occurred || '미입력'}</dd></div>
          <div><dt>메시지</dt><dd className="pre">{intake.symptom}</dd></div>
          {intake.asset && (
            <div className="asset"><dt>장비 · 보증</dt>
              <dd><span className={intake.asset.warranty === '보증 만료' ? 'lozenge lozenge-red' : 'lozenge lozenge-green'}>{intake.asset.warranty}</span> {intake.asset.warrantyNote}<br />
                <small>설치 {intake.asset.installDate} · 출하 {intake.asset.shipDate} · 이전 서비스 {intake.asset.previous}건</small></dd></div>
          )}
        </dl>
      )}
    </div>
  )
}

// Jira의 상태 드롭다운 버튼: 선택하면 이동 가능한 전환을 보여 준다.
function StatusMenu({ item, dispatch }) {
  const [open, setOpen] = useState(false)
  const can = Boolean(dispatch) && canReanalyze(item)
  return (
    <div className="status-menu">
      <button className={`status-btn status-${item.status === '종결' ? 'green' : item.status === '반려됨' ? 'red' : item.status === '추가 정보 필요' ? 'yellow' : 'blue'}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>{item.status} ▾</button>
      {open && (
        <ul className="menu" role="menu">
          <li role="none"><button role="menuitem" disabled={!can} onClick={() => { dispatch({ type: 'REANALYZE', id: item.id }); setOpen(false) }}>재분석 요청</button></li>
          {!can && <li className="muted small menu-note">이 상태에서는 다른 전환이 없습니다.</li>}
        </ul>
      )}
    </div>
  )
}

// Jira의 "This requires your approval" 패널: Approve / Decline.
function ApprovalPanel({ item, dispatch, me }) {
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState('')

  if (!item.analysis) return <div className="side-panel"><h3>검토 전</h3><p className="muted small">분석이 끝나면 근거와 부서별 초안을 검토하고 승인할 수 있습니다.</p></div>
  if (item.status === '처리 중' || item.status === '종결') return <ResolvePanel item={item} dispatch={dispatch} me={me} />
  if (item.status === '반려됨') {
    const last = [...item.comments].reverse().find((c) => c.text.startsWith('반려 사유'))
    return <div className="side-panel declined"><h3>반려됨</h3><p className="small">{last?.text}</p><p className="muted small">상태 메뉴에서 재분석을 요청할 수 있습니다.</p></div>
  }

  const approvable = Boolean(dispatch) && canApprove(item)
  return (
    <div className="side-panel approval">
      <h3>승인이 필요합니다</h3>
      <p className="small">품질 담당자가 근거와 부서별 초안을 확인한 뒤 승인하면 선택한 부서로 연결 업무가 생성됩니다. 승인 전에는 전달되지 않습니다.</p>
      {!declining ? (
        <div className="actions left">
          <button className="primary" disabled={!approvable} onClick={() => dispatch({ type: 'APPROVE', id: item.id })}>승인</button>
          <button disabled={!dispatch || !isEditable(item)} onClick={() => setDeclining(true)}>반려</button>
        </div>
      ) : (
        <div>
          <label className="small">반려 사유 (내부 메모로 남습니다)<textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus /></label>
          <div className="actions left">
            <button className="danger" disabled={!dispatch || !reason.trim()} onClick={() => { dispatch({ type: 'DECLINE', id: item.id, reason }); setDeclining(false); setReason('') }}>반려 확인</button>
            <button onClick={() => { setDeclining(false); setReason('') }}>취소</button>
          </div>
        </div>
      )}
      {!approvable && !declining && <p className="muted small">부서를 한 곳 이상 선택하고 모든 초안을 채우면 승인할 수 있습니다.</p>}
    </div>
  )
}

// 승인 후: 연결 업무가 모두 완료되면 품질 담당자가 부서 결과를 확인하고 원본 요청을 종결한다(Jira 연결 작업 완료 후 원본 해결).
function ResolvePanel({ item, dispatch, me }) {
  const [note, setNote] = useState('')
  const done = item.linked.filter((l) => l.status === '완료').length
  if (item.status === '종결') {
    return <div className="side-panel approved"><h3>종결됨</h3><p><strong>{item.resolution.by}</strong> · {formatTime(item.resolution.at)}</p>{item.resolution.note && <p className="small">{item.resolution.note}</p>}<p className="muted small">고객 포털에서 완료로 표시됩니다.</p></div>
  }
  return (
    <div className={canResolve(item) ? 'side-panel approval' : 'side-panel'}>
      <h3>부서 처리 {done}/{item.linked.length} 완료</h3>
      <p className="small">{item.approval.by}이 {formatTime(item.approval.at)}에 승인했습니다.</p>
      {canResolve(item) ? (
        <>
          <p className="small">모든 연결 업무가 완료되었습니다. 처리 결과를 확인한 뒤 요청을 종결하세요.</p>
          <label className="small">종결 메모(고객에게 보입니다)<textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></label>
          <button className="primary" disabled={!dispatch} onClick={() => dispatch({ type: 'RESOLVE', id: item.id, note })}>요청 종결</button>
        </>
      ) : <p className="muted small">부서 업무가 모두 완료되면 종결할 수 있습니다.</p>}
    </div>
  )
}

function DetailsPanel({ item, dispatch, me }) {
  const { intake, analysis } = item
  const manual = analysis?.evidence.filter((e) => e.kind === 'manual').length ?? 0
  const cases = analysis?.evidence.filter((e) => e.kind === 'fsr').length ?? 0
  const targets = item.linked.length > 0 ? item.linked.map((l) => l.name) : item.departments.filter((d) => d.selected).map((d) => d.key && ({ service: '서비스', quality: '품질', parts: '부품·자재', sales: '영업' }[d.key]))
  return (
    <div className="side-panel details">
      <h3>세부 정보</h3>
      <dl className="detail-list">
        <div><dt>담당자</dt><dd>{item.assignee ? <><Avatar name={item.assignee} /> {item.assignee}</> : <><span className="muted">미지정</span> <button className="linkish" disabled={!dispatch} onClick={() => dispatch({ type: 'ASSIGN', id: item.id })}>나에게 지정</button></>}</dd></div>
        <div><dt>접수자</dt><dd><Avatar name={intake.creator} /> {intake.creator}</dd></div>
        <div><dt>접수 사유</dt><dd>{intake.type}</dd></div>
        <div><dt>고객사</dt><dd>{intake.company}</dd></div>
        <div><dt>기계 · 호기</dt><dd>{intake.machine} · {intake.serial}</dd></div>
        <div><dt>지식 근거</dt><dd>{analysis ? `${manual + cases}건 (매뉴얼 ${manual}, 과거 사례 ${cases})` : '미분석'}</dd></div>
        <div><dt>대상 부서</dt><dd>{targets.length ? targets.join(', ') : '없음'}</dd></div>
      </dl>
      <p className="muted small">생성 {formatTime(item.createdAt)}{item.revision > 1 ? ` · 재분석 ${item.revision - 1}회` : ''}</p>
    </div>
  )
}
