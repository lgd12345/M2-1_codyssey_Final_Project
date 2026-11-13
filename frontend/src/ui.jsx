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

export const nowIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const LOZENGE = { '분석 중': 'neutral', '검토 대기': 'blue', '추가 정보 필요': 'yellow', '승인됨': 'green', '반려됨': 'red' }

// Jira의 상태 로젠지: 작은 대문자형 라벨 배지.
export function Lozenge({ status }) {
  return <span className={`lozenge lozenge-${LOZENGE[status] || 'neutral'}`}>{status}</span>
}

export function Avatar({ name }) {
  return <span className="avatar" aria-hidden="true">{(name || '?').trim().charAt(0).toUpperCase()}</span>
}
