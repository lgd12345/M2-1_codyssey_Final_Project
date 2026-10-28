import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

function App() {
  return <div className="wrap">
    <header className="top"><div className="brand"><span>S</span>Service Desk</div><div className="badge">화면 목업</div></header>
    <main>
      <div className="intro"><small>SERVICE INTAKE</small><h1>고객 서비스 접수</h1><p>고객 문의를 접수하면 관련 자료를 확인하고, 기사 전달 초안과 협업 부서를 제안하는 화면입니다.</p></div>
      <div className="grid">
        <section className="card" aria-label="고객 문의 입력 예시">
          <h2>고객 문의 입력</h2>
          <label className="label" htmlFor="product">제품 종류</label><select className="field" id="product" defaultValue="세탁기"><option>세탁기</option></select>
          <label className="label" htmlFor="model">모델명</label><input className="field" id="model" defaultValue="WM-2024" readOnly />
          <label className="label" htmlFor="type">문의 유형</label><select className="field" id="type" defaultValue="누수 / 작동 오류"><option>누수 / 작동 오류</option></select>
          <label className="label" htmlFor="inquiry">문의 내용</label><textarea className="field" id="inquiry" rows="7" defaultValue="어제부터 세탁기 아래 바닥에 물이 고입니다. 배수할 때 E3 오류가 뜨고, 이전에도 같은 증상으로 수리를 받았는데 다시 발생했습니다." readOnly />
          <button className="action" type="button">접수 내용 분석하기 →</button><p className="note">화면 구성을 보여주는 목업이며 버튼은 동작하지 않습니다.</p>
        </section>
        <div className="result">
          <section className="card"><div className="result-head"><h2>접수 분석 결과</h2><span className="mock">예시 결과</span></div><div className="summary">세탁기 · WM-2024 &nbsp; / &nbsp; 누수 및 배수 오류</div></section>
          <section className="card"><p className="section">DOCUMENT SEARCH</p><h2>관련 문서</h2><div className="source"><span className="id">KB-101</span><b>세탁기 배수 오류 점검 가이드</b><p>배수 호스 꺾임, 필터 막힘, 배수 펌프 작동 상태를 확인합니다.</p></div><div className="source"><span className="id">KB-401</span><b>누수 접수 시 현장 확인</b><p>누수 위치와 범위를 확인하고 전기 부품 주변 상태를 점검합니다.</p></div></section>
          <section className="card"><p className="section">TECHNICIAN BRIEF</p><h2>서비스 기사 전달 초안</h2><div className="draft">{`고객 문의: 세탁기 하부에 물 고임. 배수 시 E3 오류 발생. 동일 증상 수리 이력 있음.\n\n현장 확인 요청:\n1. 배수 호스 및 필터 상태 확인\n2. 누수 위치와 배수 펌프 작동 상태 확인\n3. 이전 수리 내역과 동일 증상 재발 여부 확인\n\n※ 기사 전달 전 담당자 검토가 필요합니다.`}</div></section>
          <section className="card"><p className="section">DEPARTMENT ROUTING</p><h2>추천 협업 부서</h2><div className="dept"><span className="num">01</span><div><strong>현장서비스팀</strong><p>방문 점검과 고객 일정 조율</p></div></div><div className="dept"><span className="num">02</span><div><strong>기술지원팀</strong><p>배수 오류와 누수 원인 진단 지원</p></div></div><div className="dept"><span className="num">03</span><div><strong>품질관리팀</strong><p>동일 증상 재발 및 수리 이력 검토</p></div></div></section>
        </div>
      </div>
    </main>
    <footer className="foot">Service Desk · UI Mockup</footer>
  </div>
}

createRoot(document.getElementById('root')).render(<App />)
