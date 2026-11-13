// 시연용 가상 데이터. 실제 FSR·매뉴얼·AI 분석과 연결되어 있지 않고, 내용은 FSR의 "유형"만 참고해 새로 쓴 것이다.

export const COMPANIES = ['가상고객사 A', '가상고객사 B', '가상고객사 C', '가상고객사 D']
export const MACHINES = ['VMCT-01', 'VMCT-02', 'VMCT-03', 'VMCT-04', 'VMCT-05', 'VMCT-06']

export const DEPARTMENTS = [
  { key: 'service', name: '서비스', role: '현장 점검·수리' },
  { key: 'quality', name: '품질', role: '결함 조사·재발 방지' },
  { key: 'parts', name: '부품·자재', role: '부품 수배·재고' },
  { key: 'sales', name: '영업', role: '고객 대응·보증·비용' },
]

export const ANALYSIS_STEPS = [
  { key: 'identify', title: '장비·증상 식별' },
  { key: 'manual', title: '매뉴얼 검색' },
  { key: 'cases', title: '과거 FSR 검색' },
  { key: 'compare', title: '근거 비교' },
  { key: 'route', title: '대상 부서 판단' },
  { key: 'draft', title: '부서별 초안 작성' },
]

export const REVIEW_STATUSES = ['검토 대기', '추가 정보 필요']

const dept = (selected, reason, draft = '') => ({ selected, reason, draft })

export const SCENARIOS = {
  s1: {
    id: 's1',
    label: 'ATC 신호 불량 (서비스만)',
    title: '매거진 포트 신호 불량으로 ATC 정지',
    status: '검토 대기',
    intake: {
      company: '가상고객사 A', machine: 'VMCT-02', serial: 'MACH-00231',
      symptom: '공구 교환 중 ATC 암이 멈추고 매거진 포트 UP/DOWN 신호 불량 알람이 뜹니다. 재기동하면 한두 번은 정상 동작합니다.',
      alarm: 'ATC ARM 작동 불가', occurred: '오늘 오전, 가공 중',
    },
    stepResults: { identify: 'VMCT-02 · ATC 알람 · 신호 불량', manual: '매뉴얼 2건', cases: '유사 사례 2건', compare: '매뉴얼 절차와 사례 조치가 일치', route: '서비스 1곳', draft: '초안 1건' },
    caseSearch: 'ok',
    summary: 'ATC 암 정지는 매거진 포트 UP/DOWN 확인 센서의 체결 또는 위치 이상일 가능성이 가장 높습니다. 재기동하면 간헐적으로 정상 동작하는 점이 센서 접촉·위치 불안정 가설과 맞습니다.',
    causes: [
      { title: '포트 UP/DOWN 확인 센서 체결 풀림', level: '높음', evidence: ['m1', 'f1'], detail: '매뉴얼의 포트 신호 점검 절차와 유사 사례의 조치가 일치합니다.' },
      { title: '실린더 센서 위치 틀어짐', level: '보통', evidence: ['m1'], detail: '센서를 다시 조여도 재발하면 위치 재설정이 필요합니다.' },
    ],
    questions: ['같은 알람이 특정 포트 번호에서만 발생하는지 확인이 필요합니다.'],
    evidence: [
      { id: 'm1', kind: 'manual', title: '매거진 포트 UP/DOWN 신호 점검', source: 'VMCT 정비 매뉴얼 · ATC 장', excerpt: '포트 UP/DOWN 신호가 확인되지 않으면 실린더에 부착된 확인 센서의 체결 상태와 위치를 점검한다.', note: '해당 기종 절차와 일치합니다.' },
      { id: 'f1', kind: 'fsr', title: '과거 사례 · VMCT-02', source: 'FSR-시연-0101', excerpt: '접수: 매거진 포트 UP/DOWN 신호 불량으로 ATC 작동 불가\n조치: 확인 센서 풀림 확인, 재조임 및 위치 재설정', note: '기종과 증상이 같습니다. 과거 조치이며 현재 건의 원인이 확정된 것은 아닙니다.' },
    ],
    departments: {
      service: dept(true, 'ATC 점검은 현장 서비스 업무이며 단발성 조치 사례로 보입니다.', '[서비스 점검 요청]\n- 대상: 가상고객사 A / VMCT-02 (MACH-00231)\n- 증상: ATC 암 정지, 포트 UP/DOWN 신호 불량\n- 점검 순서: 1) 포트 UP/DOWN 확인 센서 체결 상태 2) 센서 위치와 신호 3) 재설정 후 ATC 연속 동작 시험\n- 확인 요청: 알람이 발생한 포트 번호'),
      quality: dept(false, '동일 증상의 반복 이력이 확인되지 않아 단순 점검으로 판단했습니다.'),
      parts: dept(false, '교체 부품이 필요한지는 점검 후에 판단합니다.'),
      sales: dept(false, '고객 이견이나 비용 쟁점이 없습니다.'),
    },
  },
  s2: {
    id: 's2',
    label: '반복 공구 낙하 (서비스 + 품질)',
    title: '공구 낙하 반복 발생 (최근 2개월 3회)',
    status: '검토 대기',
    intake: {
      company: '가상고객사 B', machine: 'VMCT-05', serial: 'MACH-00418',
      symptom: '공구 교환 중 공구가 떨어졌습니다. 최근 두 달 사이 같은 현상이 세 번째입니다.',
      alarm: '알람 없음', occurred: '최근 2개월간 3회',
    },
    stepResults: { identify: 'VMCT-05 · 공구 낙하 · 반복 3회', manual: '매뉴얼 2건', cases: '유사 사례 4건 (동일 기종 2건)', compare: '개별 수리 사례 다수, 반복 원인은 미확인', route: '서비스 + 품질', draft: '초안 2건' },
    caseSearch: 'ok',
    summary: '공구 낙하는 ATC 암 파지부 마모나 클램프력 저하와 관련된 사례가 많습니다. 다만 같은 장비에서 반복되고 동일 기종 사례도 있어, 개별 수리를 넘어 원인 조사가 필요해 보입니다.',
    causes: [
      { title: 'ATC 암 공구 파지부 마모 또는 클램프력 저하', level: '높음', evidence: ['m1', 'f1', 'f2'], detail: '유사 사례 대부분이 암 파지부 점검과 교체로 처리되었습니다.' },
      { title: '공구 홀더 규격·풀스터드 상태', level: '보통', evidence: ['m1'], detail: '사용 공구의 상태에 따라 낙하가 생길 수 있어 확인이 필요합니다.' },
    ],
    questions: ['사용 중인 홀더 종류와 풀스터드 교체 이력을 알려 주세요.', '낙하한 공구가 특정 포트에 집중되는지 확인이 필요합니다.'],
    evidence: [
      { id: 'm1', kind: 'manual', title: 'ATC 암 공구 파지 점검', source: 'VMCT 정비 매뉴얼 · ATC 장', excerpt: '공구 교환 중 공구가 이탈하면 암의 파지부 마모와 클램프 상태, 홀더 규격을 점검한다.', note: '점검 항목으로 사용할 수 있습니다.' },
      { id: 'f1', kind: 'fsr', title: '과거 사례 · VMCT-05', source: 'FSR-시연-0202', excerpt: '접수: 공구 교환 중 공구 낙하\n조치: 암 파지부 마모 확인, 암 교체 후 교환 시험 정상', note: '같은 기종입니다. 조치가 교체였고 반복 여부는 기록되어 있지 않습니다.' },
      { id: 'f2', kind: 'fsr', title: '과거 사례 · VMCT-04', source: 'FSR-시연-0203', excerpt: '접수: 공구 낙하 현상 반복\n조치: 풀스터드 체결 불량, 규격 확인 후 교체', note: '다른 기종입니다. 원인이 달랐다는 점만 참고하세요.' },
    ],
    departments: {
      service: dept(true, '현장 점검과 암 파지부 상태 확인이 필요합니다.', '[서비스 점검 요청]\n- 대상: 가상고객사 B / VMCT-05 (MACH-00418)\n- 증상: 공구 교환 중 낙하, 최근 2개월 3회\n- 점검 순서: 1) ATC 암 파지부 마모 2) 클램프력 3) 홀더·풀스터드 상태\n- 확인 요청: 낙하가 특정 포트에 집중되는지'),
      quality: dept(true, '같은 현상이 반복되어 개별 수리를 넘어 원인 조사가 필요합니다.', '[품질 조사 요청]\n- 대상: 가상고객사 B / VMCT-05 (MACH-00418)\n- 배경: 동일 증상 최근 2개월 3회 발생\n- 요청: 동일 기종·유사 시기 생산분의 ATC 암 파지부 이력 확인, 반복 원인 조사 여부 판단\n- 참고: 동일 기종 과거 사례 1건은 암 교체로 처리됨'),
      parts: dept(false, '교체 부품이 필요하면 서비스 점검 후 요청합니다.'),
      sales: dept(false, '고객 이견이나 비용 쟁점이 확인되지 않았습니다.'),
    },
  },
  s3: {
    id: 's3',
    label: '주축 앰프 알람 (서비스 + 부품·자재)',
    title: '주축 앰프 알람으로 생산 중단',
    status: '검토 대기',
    intake: {
      company: '가상고객사 C', machine: 'VMCT-06', serial: 'MACH-00577',
      symptom: '주축 앰프 알람과 모터 센서 신호 이상이 나오고 주축이 기동되지 않습니다. 생산이 중단된 상태입니다.',
      alarm: 'SPINDLE AMP ALARM / 모터 센서 신호 이상', occurred: '어제 저녁부터',
    },
    stepResults: { identify: 'VMCT-06 · 주축 앰프 알람', manual: '매뉴얼 3건', cases: '유사 사례 3건', compare: '케이블 단선 사례가 다수, 부품 수배 필요', route: '서비스 + 부품·자재', draft: '초안 2건' },
    caseSearch: 'ok',
    summary: '주축 모터 센서 신호 이상은 피드백 케이블 단선인 사례가 가장 많습니다. 생산이 중단되었으므로 부품을 미리 수배하는 것이 복구 시간에 영향을 줍니다.',
    causes: [
      { title: '주축 모터 센서 신호선(피드백 케이블) 단선', level: '높음', evidence: ['m1', 'f1'], detail: '알람 조합이 과거 사례와 같고, 케이블 교체로 복구되었습니다.' },
      { title: '주축 앰프 불량', level: '낮음', evidence: ['m1'], detail: '케이블 점검에서 이상이 없을 때 다음 후보로 봅니다.' },
    ],
    questions: ['알람이 상시 발생하는지, 주축 동작 중에만 발생하는지 확인이 필요합니다.'],
    evidence: [
      { id: 'm1', kind: 'manual', title: '주축 앰프 알람 대응', source: 'VMCT 정비 매뉴얼 · 전장 장', excerpt: '모터 센서 신호 이상 시 피드백 케이블의 연결과 단선 여부, 앰프 상태를 순서대로 점검한다.', note: '점검 순서로 사용할 수 있습니다.' },
      { id: 'f1', kind: 'fsr', title: '과거 사례 · VMCT-06', source: 'FSR-시연-0303', excerpt: '접수: 주축 모터 센서 신호 이상, 앰프 알람 3건\n조치: 신호선 단선 확인, 임시로 다른 장비 케이블 교체 후 부품 청구·정식 교체', note: '같은 기종입니다. 임시 조치와 정식 교체가 함께 기록된 사례라 그대로 따르지 않습니다.' },
    ],
    departments: {
      service: dept(true, '현장 점검과 케이블 교체 작업이 필요합니다.', '[서비스 긴급 점검 요청]\n- 대상: 가상고객사 C / VMCT-06 (MACH-00577), 생산 중단 중\n- 증상: 주축 앰프 알람, 모터 센서 신호 이상\n- 점검 순서: 1) 피드백 케이블 연결·단선 2) 앰프 상태 3) 복구 후 주축 시험\n- 참고: 부품 수배는 부품·자재와 병행 진행'),
      quality: dept(false, '반복 이력이 확인되지 않았습니다.'),
      parts: dept(true, '케이블 교체 가능성이 높고 수배 시간이 복구 시간을 좌우합니다.', '[부품 수배 요청]\n- 대상: VMCT-06 (MACH-00577)\n- 요청: 주축 모터 피드백 케이블 재고 확인과 긴급 수배 준비\n- 사유: 서비스 점검 결과에 따라 즉시 교체가 필요할 수 있음\n- 비고: 점검 전이므로 부품 확정이 아닌 사전 준비 요청'),
      sales: dept(false, '생산 중단 상황은 서비스가 고객에게 직접 안내합니다.'),
    },
  },
  s4: {
    id: 's4',
    label: '고객 이견·비용 (서비스 + 영업)',
    title: '이전 수리 부위 누유 재발, 무상 요구',
    status: '검토 대기',
    intake: {
      company: '가상고객사 D', machine: 'VMCT-04', serial: 'MACH-00339',
      symptom: '가공 중 기계 하부로 절삭유가 흘러내립니다. 이전 수리 후 다시 발생했으니 무상으로 해결해 달라고 요구하십니다.',
      alarm: '알람 없음', occurred: '이번 주 월요일부터',
    },
    stepResults: { identify: 'VMCT-04 · 누유 · 재발 · 무상 요구', manual: '매뉴얼 2건', cases: '유사 사례 3건', compare: '실링 불량 사례 다수, 이전 조치 부위 확인 필요', route: '서비스 + 영업', draft: '초안 2건' },
    caseSearch: 'ok',
    summary: '슬라이드 커버 틈새로 절삭유가 유입되는 실링 불량이 가장 유력합니다. 이전 수리 부위와 같은지에 따라 대응이 달라지며, 고객이 무상 처리를 요구하고 있어 영업의 고객 대응이 필요합니다.',
    causes: [
      { title: '슬라이드 커버 틈새 절삭유 유입 (실링 불량)', level: '높음', evidence: ['m1', 'f1'], detail: '유사 사례 대부분이 커버 체결부 실링 처리로 해결되었습니다.' },
      { title: '이전 조치 부위의 재발', level: '보통', evidence: ['f1'], detail: '이전 수리 기록과 비교해야 확정할 수 있습니다.' },
    ],
    questions: ['이전 수리 내용과 날짜를 확인해야 재발 여부를 판단할 수 있습니다.'],
    evidence: [
      { id: 'm1', kind: 'manual', title: '슬라이드 커버 점검과 실링', source: 'VMCT 정비 매뉴얼 · 커버 장', excerpt: '커버 체결부와 겹침부의 틈을 점검하고 절삭유 유입이 있으면 실링 처리한다.', note: '점검 항목으로 사용할 수 있습니다.' },
      { id: 'f1', kind: 'fsr', title: '과거 사례 · VMCT-04', source: 'FSR-시연-0404', excerpt: '접수: 가공 중 본체에서 누유 발생\n조치: 슬라이드 커버 사이로 절삭유 유입 확인, 커버 틈새 실링 작업', note: '증상이 같습니다. 보증 처리 여부와 귀책은 이 사례로 판단하지 않습니다.' },
    ],
    departments: {
      service: dept(true, '누유 위치 점검과 실링 작업이 필요합니다.', '[서비스 점검 요청]\n- 대상: 가상고객사 D / VMCT-04 (MACH-00339)\n- 증상: 가공 중 하부 누유, 이전 수리 후 재발\n- 점검 순서: 1) 슬라이드 커버 체결부 2) 이전 수리 부위와 비교 3) 실링 후 누유 확인\n- 요청: 이전 수리 기록과 대조 결과를 영업에 공유'),
      quality: dept(false, '반복 발생 이력은 이번 건이 처음이라 우선 서비스 확인 결과를 봅니다.'),
      parts: dept(false, '실링 작업은 부품 교체 없이 가능한 경우가 많습니다.'),
      sales: dept(true, '고객이 무상 처리를 요구하고 있어 보증 범위와 비용 설명이 필요합니다.', '[영업 고객 대응 요청]\n- 대상: 가상고객사 D / VMCT-04 (MACH-00339)\n- 배경: 이전 수리 후 누유 재발, 고객이 무상 처리를 요구\n- 요청: 보증 범위와 이전 수리 내역을 확인한 뒤 고객에게 설명\n- 주의: 유·무상과 귀책은 AI가 확정하지 않으며, 서비스 점검 결과와 계약 조건으로 담당자가 판단'),
    },
  },
  s5: {
    id: 's5',
    label: '근거 부족 (추가 정보 필요)',
    title: '이상 소음 접수 (정보 부족)',
    status: '추가 정보 필요',
    intake: {
      company: '가상고객사 A', machine: 'VMCT-03', serial: 'MACH-00102',
      symptom: '기계에서 이상한 소리가 납니다.', alarm: '', occurred: '',
    },
    stepResults: { identify: 'VMCT-03 · 증상 특정 불가', manual: '일반 점검 절차 1건', cases: '과거 사례 검색이 연결되지 않았습니다', compare: '근거가 부족해 원인 후보를 제시하지 않음', route: '서비스 (정보 수집)', draft: '초안 1건' },
    caseSearch: 'unavailable',
    summary: '입력된 정보만으로는 원인 후보를 제시할 수 없습니다. 소음이 나는 위치와 조건을 먼저 확인해야 하며, 추측으로 원인을 적지 않았습니다.',
    causes: [],
    questions: ['소음이 나는 위치는 어디인가요? (주축, 이송축, 유압 장치 등)', '어떤 동작 중에 나나요? (회전, 이송, 공구 교환)', '알람이 함께 발생했나요? 언제부터인가요?', '소음의 종류는 무엇인가요? (마찰음, 타격음, 고주파음)'],
    evidence: [
      { id: 'm1', kind: 'manual', title: '이상 소음 일반 점검 순서', source: 'VMCT 정비 매뉴얼 · 일반 점검', excerpt: '소음 위치와 발생 조건을 먼저 특정한 뒤 해당 장치의 점검 절차로 진행한다.', note: '원인을 특정하는 근거가 아니라 점검 순서입니다.' },
    ],
    departments: {
      service: dept(true, '소음 위치와 조건을 확인하기 위해 현장 연락이 필요합니다.', '[정보 확인 요청]\n- 대상: 가상고객사 A / VMCT-03 (MACH-00102)\n- 접수 내용: 기계에서 이상한 소리가 남 (위치·조건 미상)\n- 요청: 고객에게 연락해 소음 위치, 발생 동작, 알람 유무, 소음 종류를 확인하고 접수 내용을 보완\n- 비고: 정보가 보완되면 재분석 예정'),
      quality: dept(false, '정보가 부족해 판단할 수 없습니다.'),
      parts: dept(false, '정보가 부족해 판단할 수 없습니다.'),
      sales: dept(false, '고객 이견이나 비용 쟁점이 없습니다.'),
    },
  },
  s5b: {
    id: 's5b',
    label: '추가 정보 반영 후 재분석',
    title: '주축 저속 회전 시 소음',
    status: '검토 대기',
    intake: null,
    stepResults: { identify: 'VMCT-03 · 주축 저속 소음', manual: '매뉴얼 2건', cases: '과거 사례 검색이 연결되지 않았습니다', compare: '매뉴얼 근거만으로 후보 제시, 신뢰도는 낮춤', route: '서비스', draft: '초안 1건' },
    caseSearch: 'unavailable',
    summary: '추가 정보로 주축 저속 회전 시 소음으로 좁혀졌습니다. 과거 사례를 아직 확인할 수 없어, 매뉴얼에 근거한 후보만 제시하며 신뢰도를 낮게 표시합니다.',
    causes: [
      { title: '주축 베어링 초기 마모 또는 윤활 상태', level: '보통', evidence: ['m1'], detail: '저속 회전 소음의 일반적인 점검 항목입니다. 사례로 확인되지는 않았습니다.' },
      { title: '구동 벨트·커플링 간섭', level: '낮음', evidence: ['m1'], detail: '베어링 점검에서 이상이 없을 때 확인합니다.' },
    ],
    questions: [],
    evidence: [
      { id: 'm1', kind: 'manual', title: '주축 회전 소음 점검', source: 'VMCT 정비 매뉴얼 · 주축 장', excerpt: '저속 회전 시 소음은 베어링 상태와 윤활, 구동부 간섭을 순서대로 점검한다.', note: '과거 사례로 뒷받침되지 않아 후보로만 사용합니다.' },
    ],
    departments: {
      service: dept(true, '주축 점검은 현장 서비스 업무입니다.', '[서비스 점검 요청]\n- 대상: VMCT-03\n- 증상: 주축 저속 회전 시 소음 (고객 추가 정보 반영)\n- 점검 순서: 1) 주축 베어링과 윤활 상태 2) 구동 벨트·커플링 간섭\n- 비고: 과거 사례 근거 없이 매뉴얼 기준으로만 작성된 초안'),
      quality: dept(false, '반복 이력이 확인되지 않았습니다.'),
      parts: dept(false, '점검 후에 판단합니다.'),
      sales: dept(false, '고객 이견이나 비용 쟁점이 없습니다.'),
    },
  },
}

export const SAMPLE_IDS = ['s1', 's2', 's3', 's4', 's5']
