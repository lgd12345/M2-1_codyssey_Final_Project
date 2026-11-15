// What the analysis bubble offers next: the departments the AI picked become mail actions. Pure helpers only.
export const CHAT_ASK_EVENT = 'morrono-chat-ask'

export const ACTIVITY_LABELS = {
  service: '서비스맨 출동 요청 메일',
  quality: '품질관리부서 보고 메일',
  parts: '부품 수배 요청 메일',
  sales: '영업 안내 메일',
}
const ORDER = ['service', 'quality', 'parts', 'sales']

export function activitiesFor(departments) {
  return ORDER.map(key => (departments ?? []).find(d => d.key === key && d.aiSelected))
    .filter(Boolean).map(d => ({ key: d.key, label: ACTIVITY_LABELS[d.key] }))
}

// Asking for a draft only: sending is always the operator's own button press on the mail card.
export const activityQuestion = activity => `${activity.label} 초안을 만들어 주세요.`

export function firstSentences(text, count) {
  const value = (text ?? '').trim()
  const sentences = value.match(/[^.!?。]+[.!?。]?\s*/g) ?? []
  if (sentences.length <= count) return { text: value, cut: false }
  return { text: sentences.slice(0, count).join('').trim(), cut: true }
}
