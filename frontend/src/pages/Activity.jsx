import React from 'react'
import { formatTime } from '../ui.jsx'

// 이력: 접수, 분석, 메일 발송, 종결처럼 누가 언제 무엇을 했는지의 기록만 시간 역순으로 보여 준다.
// 고객과의 연락은 메일과 종결 때의 처리 결과가 맡는다.
export function Activity({ item }) {
  const entries = item.history.map((h, i) => ({ id: `h${i}`, at: h.at, text: h.text }))
    .sort((x, y) => (x.at < y.at ? 1 : x.at > y.at ? -1 : 0))
  return (
    <section className="block" aria-labelledby="activity-title">
      <div className="block-head"><h2 id="activity-title">이력</h2></div>
      <ul className="activity">
        {entries.map((e) => <li key={e.id} className="event"><time>{formatTime(e.at)}</time> {e.text}</li>)}
        {entries.length === 0 && <li className="muted">표시할 이력이 없습니다.</li>}
      </ul>
    </section>
  )
}
