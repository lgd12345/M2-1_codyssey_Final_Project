// What the analysis bubble offers next: the departments the AI picked become mail actions. Pure helpers only.
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

export function firstSentences(text, count) {
  const value = (text ?? '').trim()
  const sentences = value.match(/[^.!?。]+[.!?。]?\s*/g) ?? []
  if (sentences.length <= count) return { text: value, cut: false }
  return { text: sentences.slice(0, count).join('').trim(), cut: true }
}

const REQUEST = /^CLM-\d{3,19}$/
const DEPARTMENT = /^[a-z][a-z0-9_]{1,30}$/
function check(id, key) {
  if (!REQUEST.test(id ?? '') || (key !== undefined && !DEPARTMENT.test(key ?? ''))) throw new Error('올바르지 않은 메일 주소입니다.')
}
// The mail window starts from a fixed template and the department key only; the server finds the addresses.
export const mailTemplateUrl = (id, key) => { check(id, key); return `/service-requests/${id}/mail-template?department_key=${key}` }
export const mailAiUrl = id => { check(id); return `/service-requests/${id}/mail-template/ai` }
