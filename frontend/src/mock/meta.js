// 시나리오별 보조 데이터(시연용 가상). Jira 요청 유형, TRUMPF 접수 사유, Siemens Copilot의 단계·권장 부품 구성에 대응한다.

export const CALL_REASONS = ['기계 고장', '기술 문의', '부품 문의', '교육·기술지원']

export const DEPT_PREFIX = { service: 'SVC', quality: 'QLT', parts: 'PRT', sales: 'SAL' }

// 등록 장비 정보(시연용 가상). TRUMPF·Philips·DMG MORI 포털처럼 접수 시점에 장비·보증 정보를 함께 보여 준다.
export const ASSETS = {
  'MACH-00231': { warranty: '보증 기간 내', warrantyNote: '내구 1년 · 2027-03-14까지', installDate: '2026-03-15', shipDate: '2026-03-02', previous: 1 },
  'MACH-00418': { warranty: '보증 기간 내', warrantyNote: '내구 1년 · 2027-01-20까지', installDate: '2026-01-21', shipDate: '2026-01-08', previous: 3 },
  'MACH-00577': { warranty: '보증 기간 내', warrantyNote: '내구 1년 · 2027-06-09까지', installDate: '2026-06-10', shipDate: '2026-05-27', previous: 0 },
  'MACH-00339': { warranty: '보증 만료', warrantyNote: '내구 1년 · 2026-08-30 만료', installDate: '2025-08-31', shipDate: '2025-08-18', previous: 2 },
  'MACH-00102': { warranty: '보증 기간 내', warrantyNote: '내구 1년 · 2027-02-11까지', installDate: '2026-02-12', shipDate: '2026-01-30', previous: 0 },
}

// 시연에서 보는 화면(역할). 고객 포털 / 담당자 대기열 / 부서 업무함으로 나뉜다.
export const VIEWS = [
  { key: 'customer', label: '고객 포털' },
  { key: 'quality', label: '품질 담당자' },
  { key: 'dept', label: '부서 업무함' },
]
export const CUSTOMER_COMPANIES = ['가상고객사 A', '가상고객사 B', '가상고객사 C', '가상고객사 D']

export const META = {
  s1: {
    type: '기계 고장', creator: '김현장 (가상고객사 A)',
    steps: ['포트 UP/DOWN 확인 센서의 체결 상태를 점검합니다.', '센서 위치와 신호를 확인합니다.', '재설정 후 ATC를 연속 동작시켜 재현 여부를 확인합니다.'],
    parts: [],
  },
  s2: {
    type: '기계 고장', creator: '이정비 (가상고객사 B)',
    steps: ['ATC 암 파지부 마모를 점검합니다.', '클램프력을 측정합니다.', '홀더와 풀스터드의 상태·규격을 확인합니다.', '낙하가 특정 포트에 집중되는지 기록합니다.'],
    parts: [{ name: 'ATC 암 파지부', note: '마모가 확인되면 교체 후보입니다. 점검 후에 판단합니다.', source: '과거 사례 FSR-시연-0202' }],
  },
  s3: {
    type: '기계 고장', creator: '박공정 (가상고객사 C)',
    steps: ['피드백 케이블의 연결과 단선 여부를 확인합니다.', '앰프 상태를 확인합니다.', '복구 후 주축 시험 운전을 합니다.'],
    parts: [{ name: '주축 모터 피드백 케이블', note: '단선이 확인되면 교체가 필요합니다. 사전 수배를 권장합니다.', source: '과거 사례 FSR-시연-0303' }],
  },
  s4: {
    type: '기계 고장', creator: '최관리 (가상고객사 D)',
    steps: ['슬라이드 커버 체결부와 겹침부의 틈을 점검합니다.', '이전 수리 부위와 비교합니다.', '실링 처리 후 누유 여부를 확인합니다.'],
    parts: [{ name: '실링재', note: '부품 교체 없이 실링 작업으로 해결된 사례가 많습니다.', source: 'VMCT 정비 매뉴얼 · 커버 장' }],
  },
  s5: {
    type: '기술 문의', creator: '김현장 (가상고객사 A)',
    steps: ['소음 위치와 발생 조건을 먼저 특정합니다.'],
    parts: [],
  },
  s5b: {
    type: '기술 문의', creator: '김현장 (가상고객사 A)',
    steps: ['주축 베어링과 윤활 상태를 점검합니다.', '구동 벨트·커플링 간섭을 확인합니다.'],
    parts: [],
  },
}
