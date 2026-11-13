// Product vocabulary, not seeded records or simulated analysis stages.
export const CALL_REASONS = ['기계 고장', '기술 문의', '부품 문의', '교육·기술지원']
export const DEPT_PREFIX = { service: 'SVC', quality: 'QLT', parts: 'PRT', sales: 'SAL' }
export const DEPARTMENTS = [
  { key: 'service', name: '서비스', role: '현장 점검·수리' },
  { key: 'quality', name: '품질', role: '결함 조사·재발 방지' },
  { key: 'parts', name: '부품·자재', role: '부품 수배·재고' },
  { key: 'sales', name: '영업', role: '고객 대응·보증·비용' },
]
