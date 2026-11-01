// Example questions for the test screen. The label says how the question is answered (not which document
// it concerns: documents have no type). Each question with a cited answer was checked against the registered
// manuals: the page that answers it came back in the search results. Re-check them when the documents change.
export const SAMPLES = [
  { label: '알람 번호', question: '알람 2026 COOLANT PUMP MOTOR OVERLOAD의 원인과 조치 방법을 알려줘.' },
  { label: '증상', question: '공구 교환 중 ATC 암이 올라오지 않을 때 어떤 알람이 뜨고 무엇을 확인해?' },
  { label: 'PMC 주소', question: 'PMC 주소 X0004.7은 무엇을 의미해?' },
  { label: '품번', question: '부품번호 2064-01-101-01의 명칭을 원본 페이지로 확인해줘.' },
  { label: '도면번호', question: '도면번호 2064-05-003-03은 어떤 부품이고 어느 쪽에 있어?' },
  { label: '절차', question: '원점 조정은 어떻게 해?' },
  { label: '안전', question: '비상정지 스위치는 어떤 역할이고 눌렀을 때 기계는 어떻게 돼?' },
  { label: '내용 질문', question: 'FANUC NC 클레임을 접수할 때 함께 받아야 할 식별 정보는 뭐야?' },
  { label: '내용 질문', question: 'VMCT 기종 자료에서 연도와 기종명이 같아도 확인해야 할 부분은?' },
  // The two below are not meant to produce a cited answer; they show the other outcomes.
  { label: '인사', question: '안녕하세요, 무엇을 물어볼 수 있나요?' },
  { label: '문서에 없는 내용', question: '서보모터 과열 시 점검 순서를 알려줘.' },
]
