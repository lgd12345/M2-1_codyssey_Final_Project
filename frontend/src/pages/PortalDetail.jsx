import React, { useState } from 'react'
import { customerStatus } from '../domain/workflow.js'
import { customerEvents } from '../domain/actions.js'
import { Modal, formatDate, formatTime } from '../ui.jsx'

const TONE = { 접수됨: 'neutral', '확인 중': 'blue', '정보 요청': 'yellow', '처리 중': 'blue', 완료: 'green' }
const TABS = [['history', '이력'], ['guides', '기술 가이드'], ['contact', '연락처']]

// TRUMPF 서비스 케이스 상세: 요청 번호·접수자·접수일·기계·설명, 정보 추가 / 콜백 요청 / 종결 요청,
// 기술 가이드·이력·연락처 탭. 이 화면에는 AI 분석, 내부 메모, 부서 초안이 나오지 않는다.
export function PortalDetail({ item, dispatch }) {
  const [tab, setTab] = useState('history')
  const [modal, setModal] = useState(null) // 'info' | 'callback' | 'close'
  const [text, setText] = useState('')
  if (!item) return <section className="center-card"><h1>서비스 요청을 찾을 수 없습니다</h1><a href="#/portal">내 서비스 요청으로</a></section>

  const status = customerStatus(item)
  const done = status === '완료'
  const unavailable = !dispatch || done
  const guides = item.guides ?? []
  const lastAsk = [...item.comments].reverse().find((c) => c.kind === 'public')
  const events = customerEvents(item)
  const closeModal = () => { setModal(null); setText('') }
  const send = (type, extra) => { dispatch({ type, id: item.id, ...extra }); closeModal() }

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
            <div><dt>기계</dt><dd>{item.intake.machine} · {item.intake.serial}</dd></div>
            <div><dt>상태</dt><dd><span className={`lozenge lozenge-${TONE[status]}`}>{status}</span></dd></div>
          </dl>
          <p className="pd-desc"><strong>설명</strong><br />{item.intake.symptom}</p>
        </div>
        <div className="pd-actions">
          <button disabled={unavailable} onClick={() => setModal('info')}>정보 추가</button>
          <button disabled={unavailable} onClick={() => setModal('callback')}>콜백 요청</button>
          <button disabled={unavailable} onClick={() => setModal('close')}>종결 요청</button>
        </div>
      </div>

      {status === '정보 요청' && lastAsk && (
        <div className="notice warn" role="status">
          <strong>서비스 담당자가 추가 정보를 요청했습니다.</strong>
          <p>{lastAsk.text}</p>
          <button className="primary" disabled={unavailable} onClick={() => setModal('info')}>정보 추가</button>
        </div>
      )}
      {done && <div className="notice ok" role="status"><strong>이 서비스 요청은 완료되었습니다.</strong>{item.resolution?.note && <p>{item.resolution.note}</p>}</div>}
      {item.closeRequested && !done && <div className="notice warn" role="status">종결을 요청했습니다. 담당자가 확인하면 완료 처리됩니다.</div>}

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
                <ul className="guides">{guides.map((g) => <li key={g.id}><div><strong>{g.title}</strong><small>{g.source}</small></div><span className="muted">PDF 열람 미연결</span></li>)}</ul>
              </>
            )}
          </>
        )}
        {tab === 'contact' && (
          <>
            <h2>저장된 연락처</h2>
            <dl className="kv"><div><dt>이름</dt><dd>{item.intake.contact?.name || '-'}</dd></div><div><dt>전화번호</dt><dd>{item.intake.contact?.phone || '-'}</dd></div><div><dt>이메일</dt><dd>{item.intake.contact?.email || '-'}</dd></div></dl>
            <p className="muted small">서비스 담당자가 이 연락처로 연락드립니다. 회사의 모든 직원이 이 요청을 확인할 수 있습니다.</p>
          </>
        )}
      </div>

      {modal === 'info' && (
        <Modal title="정보 추가" onClose={closeModal}>
          <label>메시지 *<textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} autoFocus placeholder="추가로 알려 드릴 내용을 적어 주세요." /></label>
          <div className="modal-actions"><button onClick={closeModal}>취소</button><button className="primary" disabled={!text.trim()} onClick={() => send('CUSTOMER_REPLY', { text })}>전송</button></div>
        </Modal>
      )}
      {modal === 'callback' && (
        <Modal title="콜백 요청" onClose={closeModal}>
          <p>저장된 연락처({item.intake.contact?.phone || '미입력'})로 서비스 담당자가 전화드립니다.</p>
          <div className="modal-actions"><button onClick={closeModal}>취소</button><button className="primary" onClick={() => send('CUSTOMER_CALLBACK')}>요청</button></div>
        </Modal>
      )}
      {modal === 'close' && (
        <Modal title="서비스 요청 종결 요청" onClose={closeModal}>
          <label>종결 사유 *<textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} autoFocus /></label>
          <div className="modal-actions"><button onClick={closeModal}>취소</button><button className="primary" disabled={!text.trim()} onClick={() => send('CUSTOMER_CLOSE_REQUEST', { reason: text })}>전송</button></div>
        </Modal>
      )}
    </article>
  )
}
