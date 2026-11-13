import React from 'react'
import { HOME, VIEW_OF_ROUTE, homeForRole, isStaff } from './navigation.js'

// MORRONO 사이트 화면. 메인·고객센터·헤더·푸터는 이전 메인화면(site.css) 디자인을 그대로 쓴다.

export function Icon({ name = 'arrow', ...props }) {
  const paths = {
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    diagonal: <path d="M6 18 18 6M6 6h12v12" />,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
    moon: <path d="M20.5 13A8.7 8.7 0 0 1 11 3.5 8.7 8.7 0 1 0 20.5 13Z" />,
    system: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8m-4-4v4" /></>,
    user: <><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></>,
  }
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name] || paths.arrow}</svg>
}

const themes = ['system', 'light', 'dark']
const themeLabels = { system: '시스템 설정', light: '라이트', dark: '다크' }

// 헤더 아래 작은 영문 라벨은 지금 어느 영역에 있는지 알려 준다.
const AREA_LABEL = { public: 'MACHINE SUPPORT', customer: 'CUSTOMER SERVICE', staff: 'OPERATIONS' }

export function SiteHeader({ preference, theme, session, route, pending = false, onSignOut }) {
  const next = themes[(themes.indexOf(preference) + 1) % themes.length]
  const label = `화면 테마: ${themeLabels[preference]}. 다음 테마: ${themeLabels[next]}`
  const authenticated = session?.authenticated === true
  const role = session?.user?.role
  const view = VIEW_OF_ROUTE[route.name]
  const area = !authenticated ? 'public' : view === 'customer' ? 'customer' : 'staff'
  const brandHref = authenticated ? homeForRole(role) : '#/home'
  const current = (names) => (names.includes(route.name) ? 'page' : undefined)

  return <header className={`app-header site-header ${authenticated ? 'workspace-header' : ''}`}>
    <a className="site-brand" href={brandHref} aria-label={`MORRONO ${AREA_LABEL[area]}`}>
      <span className="brand-symbol" aria-hidden="true"><i /><i /><i /><i /></span>
      <span>MORRONO<small>{AREA_LABEL[area]}</small></span>
    </a>
    {authenticated ? (isStaff(role) ? <nav className="site-nav" aria-label="업무 메뉴">
      <a href={HOME.quality} aria-current={current(['list', 'new', 'detail'])}>대기열</a>
      <a href={HOME.dept} aria-current={current(['work-list', 'work-detail'])}>받은 업무</a>
    </nav> : <nav className="site-nav" aria-label="고객 메뉴">
      <a href={HOME.customer} aria-current={current(['portal-list', 'portal-new', 'portal-detail'])}>내 서비스 요청</a>
    </nav>) : !pending ? <nav className="site-nav" aria-label="주 메뉴">
      <a className="intro-link" href="#/home" onClick={(e) => { if (route.name === 'home') { e.preventDefault(); document.getElementById('machines')?.scrollIntoView() } }}>공작기계 소개</a>
      <a href="#/support" aria-current={current(['support'])}>고객센터</a>
    </nav> : null}
    <div className="header-utilities">
      {authenticated ? <><span className="header-account" title={session.user?.login_id}>{session.user?.login_id}</span><button className="header-signout" onClick={onSignOut}>로그아웃</button></>
        : pending ? <span className="header-session-status">확인 중</span> : <a className="header-login" href="#/login">로그인<Icon name="diagonal" /></a>}
      <span className="utility-divider" aria-hidden="true" />
      <button className="theme-toggle" aria-label={label} title={label} onClick={() => theme.setPreference(next)}><Icon name={preference === 'light' ? 'sun' : preference === 'dark' ? 'moon' : 'system'} /></button>
    </div>
  </header>
}

export function SiteFooter({ staff = false }) {
  return <footer className="site-footer">
    <div><a className="footer-wordmark" href={staff ? HOME.quality : '#/home'}>MORRONO</a><span>{staff ? '운영진 업무 지원' : '공작기계 고객지원'}</span></div>
    <p>AI가 생성한 답변은 인용된 근거와 원본 매뉴얼을 함께 확인해 주세요.</p>
    {!staff && <details className="photo-credits"><summary>사진 출처</summary><div>
      <p>공작기계 사진: <a href="https://unsplash.com/photos/O5rSp_U-Pa0" target="_blank" rel="noreferrer noopener">Jelifer Maniago</a> · <a href="https://unsplash.com/photos/sxtClAGwRck" target="_blank" rel="noreferrer noopener">aluminum Zheng ji</a> / Unsplash</p>
      <a href="https://unsplash.com/license" target="_blank" rel="noreferrer noopener">Unsplash License</a><span> · 소개를 위한 예시 사진입니다.</span>
    </div></details>}
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
      <div className="hero-bottom"><span>MACHINE TOOLS &amp; CUSTOMER SUPPORT</span><a href="#/home" onClick={(e) => { e.preventDefault(); document.getElementById('machines')?.scrollIntoView({ behavior: 'smooth' }) }}>공작기계 알아보기 <span aria-hidden="true">↓</span></a></div>
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

// 고객센터: 지금은 발급받은 계정으로 로그인하는 길만 안내한다(회원가입·비회원 문의는 아직 정해지지 않아 뺐다).
export function SupportPage() {
  return <section className="support-page section-container" aria-labelledby="support-title">
    <p className="eyebrow">CUSTOMER SUPPORT</p><h1 id="support-title">무엇을 도와드릴까요?</h1><p className="page-description">이용 방법을 선택해 주세요. 필요한 지원으로 이어드립니다.</p>
    <div className="support-options signed-in">
      <a className="support-option" href="#/login"><Icon name="user" /><span className="option-kicker">MEMBER</span><h2>로그인</h2><p>발급받은 계정으로<br />서비스 요청과 진행 상황을 확인하세요.</p><span className="option-action">로그인하기<Icon /></span></a>
    </div>
    <p className="service-note">현재는 발급받은 계정으로 로그인할 수 있습니다. 온라인 회원가입과 비회원 문의는 준비 중입니다.</p>
  </section>
}
