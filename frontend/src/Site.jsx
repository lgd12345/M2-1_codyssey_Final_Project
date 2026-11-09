import React from 'react'

export function Icon({ name = 'arrow', ...props }) {
  const paths = {
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    diagonal: <path d="M6 18 18 6M6 6h12v12" />,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
    moon: <path d="M20.5 13A8.7 8.7 0 0 1 11 3.5 8.7 8.7 0 1 0 20.5 13Z" />,
    system: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8m-4-4v4" /></>,
    message: <path d="M20 15a3 3 0 0 1-3 3H9l-6 3V6a3 3 0 0 1 3-3h11a3 3 0 0 1 3 3Zm-12-7h8M8 12h5" />,
    user: <><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
  }
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name] || paths.arrow}</svg>
}

const themes = ['system', 'light', 'dark']
const themeLabels = { system: '시스템 설정', light: '라이트', dark: '다크' }

export function SiteHeader({ preference, theme, authenticated, page }) {
  const next = themes[(themes.indexOf(preference) + 1) % themes.length]
  const label = `화면 테마: ${themeLabels[preference]}. 다음 테마: ${themeLabels[next]}`
  return <header className="app-header site-header">
    <a className="site-brand" href="#/home" aria-label="MORRONO 공작기계 고객지원 홈">
      <span className="brand-symbol" aria-hidden="true"><i /><i /><i /><i /></span>
      <span>MORRONO<small>MACHINE SUPPORT</small></span>
    </a>
    <nav className="site-nav" aria-label="주 메뉴">
      <a className="intro-link" href="#machines">공작기계 소개</a>
      <a href="#/support" aria-current={page === 'support' ? 'page' : undefined}>고객센터</a>
    </nav>
    <div className="header-utilities">
      <a className="header-login" href={authenticated ? '#/workspace' : '#/login'}>{authenticated ? '내 서비스' : '로그인'}<Icon name="diagonal" /></a>
      <span className="utility-divider" aria-hidden="true" />
      <button className="theme-toggle" aria-label={label} title={label} onClick={() => theme.setPreference(next)}><Icon name={preference === 'light' ? 'sun' : preference === 'dark' ? 'moon' : 'system'} /></button>
    </div>
  </header>
}

export function SiteFooter() {
  return <footer className="site-footer">
    <div><a className="footer-wordmark" href="#/home">MORRONO</a><span>공작기계 고객지원</span></div>
    <p>AI가 생성한 답변은 인용된 근거와 원본 매뉴얼을 함께 확인해 주세요.</p>
    <details className="photo-credits"><summary>사진 출처</summary><div>
      <p>공작기계 사진: <a href="https://unsplash.com/photos/O5rSp_U-Pa0" target="_blank" rel="noreferrer noopener">Jelifer Maniago</a> · <a href="https://unsplash.com/photos/sxtClAGwRck" target="_blank" rel="noreferrer noopener">aluminum Zheng ji</a> / Unsplash</p>
      <a href="https://unsplash.com/license" target="_blank" rel="noreferrer noopener">Unsplash License</a><span> · 소개를 위한 예시 사진입니다.</span>
    </div></details>
  </footer>
}

export function HomePage() {
  return <div className="home-page">
    <section className="home-hero" aria-labelledby="hero-title">
      <img className="hero-image" src="/images/cnc-machining.jpg" width="2000" height="1125" alt="금속 공작물 위에 위치한 CNC 밀링 공구" fetchPriority="high" />
      <div className="hero-shade" />
      <div className="hero-copy">
        <p className="eyebrow">PRECISION IN EVERY DETAIL</p>
        <h1 id="hero-title">정밀한 기술,<br />끊김 없는 현장.</h1>
        <p className="hero-description">공작기계의 이해부터 필요한 지원까지.<br />현장을 위한 연결을 시작합니다.</p>
        <a className="site-button hero-cta" href="#/support">고객센터 문의<Icon name="diagonal" /></a>
      </div>
      <div className="hero-bottom"><span>MACHINE TOOLS &amp; CUSTOMER SUPPORT</span><a href="#machines">공작기계 알아보기 <span aria-hidden="true">↓</span></a></div>
    </section>

    <section id="machines" className="machine-intro section-container" aria-labelledby="machines-title">
      <div className="section-heading"><p className="eyebrow">01 / MACHINE TOOLS</p><h2 id="machines-title">가능성을 만드는<br />정밀함의 시작.</h2></div>
      <div className="machine-layout">
        <div className="machine-photo"><img src="/images/cnc-detail.jpg" width="1000" height="668" loading="lazy" alt="절삭유를 공급하며 금속을 가공하는 CNC 공작기계" /><span>CNC MACHINING / 가공 예시</span></div>
        <div className="machine-copy"><p className="section-lead">소재에 새로운 형태를,<br />현장에 더 나은 가능성을.</p><p className="muted">공작기계는 금속을 정밀하게 가공해 다양한 산업의 부품을 만듭니다. 작업에 맞는 기계를 이해하는 것에서 시작해 보세요.</p>
          <dl className="machine-types"><div><dt><span>01</span>머시닝센터</dt><dd>회전하는 공구로 밀링·드릴링 등 다양한 가공을 수행합니다.</dd></div><div><dt><span>02</span>CNC 선반</dt><dd>공작물을 회전시켜 원통형 부품 등을 가공합니다.</dd></div></dl>
        </div>
      </div>
    </section>

    <section className="support-band" aria-labelledby="home-support-title"><div className="section-container support-band-inner"><div><p className="eyebrow">02 / CUSTOMER SUPPORT</p><h2 id="home-support-title">필요한 순간,<br />더 가까운 고객지원.</h2><p>문의 방법과 서비스 이용 안내를 확인해 보세요.</p></div><a className="site-button" href="#/support">고객센터 바로가기<Icon /></a></div></section>
  </div>
}

export function SupportPage() {
  return <section className="support-page section-container" aria-labelledby="support-title">
    <p className="eyebrow">CUSTOMER SUPPORT</p><h1 id="support-title">무엇을 도와드릴까요?</h1><p className="page-description">이용 방법을 선택해 주세요. 필요한 지원으로 이어드립니다.</p>
    <div className="support-options">
      <a className="support-option" href="#/login"><Icon name="user" /><span className="option-kicker">MEMBER</span><h2>로그인</h2><p>발급받은 계정으로<br />기존 지원 서비스를 이용하세요.</p><span className="option-action">로그인하기<Icon /></span></a>
      <a className="support-option" href="#/register"><Icon name="plus" /><span className="option-kicker">JOIN US</span><h2>회원가입 안내</h2><p>처음 방문하셨나요?<br />계정 이용 안내를 확인하세요.</p><span className="option-action">안내 확인<Icon /></span></a>
      <a className="support-option" href="#/guest"><Icon name="message" /><span className="option-kicker">GUEST</span><h2>비회원 문의 안내</h2><p>계정 없이 문의하는 방법과<br />이용 준비 현황을 확인하세요.</p><span className="option-action">안내 확인<Icon /></span></a>
    </div>
    <p className="service-note">현재는 발급받은 계정으로 로그인할 수 있습니다. 온라인 회원가입과 비회원 문의는 준비 중입니다.</p>
  </section>
}

export function AccessGuide({ kind }) {
  const guest = kind === 'guest'
  return <section className="access-guide section-container" aria-labelledby="guide-title"><a className="back-link" href="#/support">← 고객센터</a><div className="guide-content"><p className="eyebrow">{guest ? 'GUEST SUPPORT' : 'MEMBERSHIP'}</p><span className="preparing-label">서비스 준비 중</span><h1 id="guide-title">{guest ? '비회원 문의를 준비하고 있습니다.' : '온라인 회원가입을 준비하고 있습니다.'}</h1><p>{guest ? '계정 없이 본인 확인 후 문의하고, 본인의 문의 내용을 조회할 수 있는 서비스를 준비하고 있습니다.' : '회사를 확인하고 계정을 신청할 수 있는 서비스를 준비하고 있습니다.'}</p><p className="muted">현재 이 화면에서는 개인정보를 입력받거나 문의를 접수하지 않습니다. 이미 계정을 발급받으셨다면 로그인해 주세요.</p><a className="site-button" href="#/login">기존 계정으로 로그인<Icon /></a></div></section>
}
