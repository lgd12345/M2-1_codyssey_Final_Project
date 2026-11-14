// Product vocabulary, not seeded records or simulated analysis stages.
export const CALL_REASONS = ['공구 교환 이상', '스핀들 이상', '이송축 이상', '유압·공압·윤활 이상', '알람·전장 이상', '가공 정밀도 이상', '부품 교체·문의', '교육·기술지원', '기타 증상']
export const DEPT_PREFIX = { service: 'SVC', quality: 'QLT', parts: 'PRT', sales: 'SAL' }
export const DEPARTMENTS = [
  { key: 'service', name: '서비스', role: '현장 점검·수리' },
  { key: 'quality', name: '품질', role: '결함 조사·재발 방지' },
  { key: 'parts', name: '부품·자재', role: '부품 수배·재고' },
  { key: 'sales', name: '영업', role: '고객 대응·보증·비용' },
]
