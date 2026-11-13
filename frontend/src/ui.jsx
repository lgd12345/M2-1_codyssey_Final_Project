import React from 'react'

const pad = (n) => String(n).padStart(2, '0')

export function formatTime(at) {
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return ''
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatDate(at) {
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? '' : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const LOZENGE = { '접수됨': 'neutral', '분석 중': 'neutral', '검토 대기': 'blue', '추가 정보 필요': 'yellow', '처리 중': 'blue', '반려됨': 'red', '종결': 'green', '전달됨': 'blue', '진행 중': 'yellow', '완료': 'green' }

// Jira의 상태 로젠지: 작은 대문자형 라벨 배지.
export function Lozenge({ status }) {
  return <span className={`lozenge lozenge-${LOZENGE[status] || 'neutral'}`}>{status}</span>
}

// TRUMPF식 모달: 제목, 닫기(×), 본문. 배경을 누르거나 Esc를 누르면 닫힌다.
export function Modal({ title, onClose, children }) {
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <button type="button" className="modal-x" onClick={onClose} aria-label="닫기">×</button>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  )
}

export function Avatar({ name }) {
  return <span className="avatar" aria-hidden="true">{(name || '?').trim().charAt(0).toUpperCase()}</span>
}
