import React from 'react'
import { customerStatus } from '../domain/workflow.js'
import { customerEvents } from '../domain/actions.js'
import { formatDate, formatTime } from '../ui.jsx'

const TONE = { 접수됨: 'neutral', '처리 중': 'blue', 완료: 'green' }

// 고객은 접수한 요청의 진행과 처리 결과만 확인한다. AI 분석·매뉴얼·내부 정보는 표시하지 않는다.
export function PortalDetail({ item }) {
  if (!item) return <section className="center-card"><h1>서비스 요청을 찾을 수 없습니다</h1><a href="#/portal">내 서비스 요청으로</a></section>

  const status = customerStatus(item)
  const done = status === '완료'
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

      <section className="panel pd-panel" aria-labelledby="pd-history-title">
        <h2 id="pd-history-title">요청 이력</h2>
        <ul className="activity portal-events">
          {events.map((e) => (
            <li key={e.id} className="event">
              <div><p className="comment-meta"><strong>{e.who}</strong> <time>{formatTime(e.at)}</time></p><p className="comment-text">{e.text}</p></div>
            </li>
          ))}
        </ul>
      </section>
    </article>
  )
}
