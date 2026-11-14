import React, { useState } from 'react'
import { customerStatus } from '../domain/workflow.js'
import { customerEvents } from '../domain/actions.js'
import { formatDate, formatTime } from '../ui.jsx'
import { SourcePageButton } from './SourcePage.jsx'

const TONE = { 접수됨: 'neutral', '확인 중': 'blue', '처리 중': 'blue', 완료: 'green' }
const TABS = [['history', '이력'], ['guides', '기술 가이드']]

// TRUMPF 서비스 케이스 상세: 요청 번호·접수자·접수일·기계·설명과 기술 가이드·이력 탭.
// 고객은 접수한 요청의 진행을 확인할 뿐 접수 이후에 하는 작업은 없다. AI 분석, 내부 메모, 부서 초안은 나오지 않는다.
export function PortalDetail({ item }) {
  const [tab, setTab] = useState('history')
  if (!item) return <section className="center-card"><h1>서비스 요청을 찾을 수 없습니다</h1><a href="#/portal">내 서비스 요청으로</a></section>

  const status = customerStatus(item)
  const done = status === '완료'
  const guides = item.guides ?? []
  const events = customerEvents(item)

  return (
    <article className="portal-detail" aria-labelledby="pd-title">
      <a className="back" href="#/portal">← 내 서비스 요청</a>
      <div className="pd-head">
        <div>
          <h1 id="pd-title">{item.intake.machine} · {item.title}</h1>
          <dl className="pd-meta">
            <div><dt>요청 번호</dt><dd>{item.id}</dd></div>
            <div><dt>접수자</dt><dd>{item.intake.creator}</dd></div>
            <div><dt>접수일</dt><dd>{formatDate(item.createdAt)}</dd></div>
            <div><dt>기계</dt><dd>{item.intake.machine}</dd></div>
            <div><dt>상태</dt><dd><span className={`lozenge lozenge-${TONE[status]}`}>{status}</span></dd></div>
          </dl>
          <p className="pd-desc"><strong>설명</strong><br />{item.intake.symptom}</p>
        </div>
      </div>

      {done && <div className="notice ok" role="status"><strong>이 서비스 요청은 완료되었습니다.</strong>{item.resolution?.note && <p>{item.resolution.note}</p>}</div>}

      <div className="quick" role="tablist" aria-label="요청 상세">
        {TABS.map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'quick-btn active' : 'quick-btn'} onClick={() => setTab(key)}>{label}</button>)}
      </div>

      <div className="panel pd-panel" role="tabpanel">
        {tab === 'history' && (
          <>
            <h2>요청 이력</h2>
            <ul className="activity portal-events">
              {events.map((e) => (
                <li key={e.id} className={e.message ? 'comment' : 'event'}>
                  <div><p className="comment-meta"><strong>{e.who}</strong> <time>{formatTime(e.at)}</time></p><p className="comment-text">{e.text}</p></div>
                </li>
              ))}
            </ul>
          </>
        )}
        {tab === 'guides' && (
          <>
            <h2>기술 가이드</h2>
            {guides.length === 0 ? <p className="muted">입력하신 내용에 해당하는 기술 가이드가 아직 없습니다.</p> : (
              <>
                <p className="muted small">접수한 증상과 오류 번호를 기준으로 스스로 확인해 볼 수 있는 자료입니다.</p>
                <ul className="guides">{guides.map((g) => <li key={g.id}><div><strong>{g.title}</strong><small>{g.source}</small></div>{g.viewable ? <SourcePageButton itemId={item.id} evidenceId={g.id} title={g.title} /> : <span className="muted small">원본 페이지 정보 없음</span>}</li>)}</ul>
              </>
            )}
          </>
        )}
      </div>

    </article>
  )
}
