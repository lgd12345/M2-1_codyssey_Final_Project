import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { buildSync } from 'esbuild'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const appRequire = createRequire(import.meta.url)
const compiled = buildSync({ entryPoints: [fileURLToPath(new URL('./Site.jsx', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false,
  external: ['react', 'react-dom', 'react-dom/*'], logLevel: 'silent' }).outputFiles[0].text
const loaded = { exports: {} }
new Function('require', 'module', 'exports', compiled)(appRequire, loaded, loaded.exports)
const { SiteHeader, SupportPage, SiteFooter } = loaded.exports
const theme = { setPreference() {} }
const header = (props) => renderToStaticMarkup(React.createElement(SiteHeader, { preference: 'light', theme, ...props }))

test('operator headers expose workspace navigation and logout without public or signup links', () => {
  for (const role of ['admin', 'user']) {
    const html = header({ session: { authenticated: true, user: { role, login_id: 'operator-demo' } }, page: 'companies' })
    for (const text of ['운영진 메뉴', '매뉴얼', '고객사 관리', '로그아웃', 'operator-demo']) assert(html.includes(text))
    for (const href of ['#/home', '#/login', '#/register', '#/guest', '#/support', '#machines']) assert(!html.includes(`href="${href}"`))
    assert.match(html, /href="#\/companies" aria-current="page"/)
    assert(!html.includes('내 서비스'))
  }
})

test('customer navigation and support lead to customer services without repeating signup or operator links', () => {
  const html = header({ session: { authenticated: true, user: { role: 'customer', login_id: 'customer@example.org' } }, page: 'workspace' })
  assert(html.includes('고객 메뉴') && html.includes('고객지원') && html.includes('로그아웃'))
  for (const href of ['#/companies', '#/login', '#/register', '#/guest']) assert(!html.includes(`href="${href}"`))
  const support = renderToStaticMarkup(React.createElement(SupportPage, { signedIn: true }))
  assert(support.includes('href="#/workspace"'))
  for (const href of ['#/login', '#/register', '#/guest']) assert(!support.includes(`href="${href}"`))
})

test('anonymous public navigation survives while unresolved protected sessions do not advertise a role', () => {
  const publicHtml = header({ session: { authenticated: false }, page: 'home' })
  assert(publicHtml.includes('공작기계 소개') && publicHtml.includes('href="#/login"'))
  const pendingHtml = header({ session: null, pending: true, page: 'companies' })
  assert(pendingHtml.includes('확인 중'))
  for (const href of ['#/companies', '#/login', '#/support']) assert(!pendingHtml.includes(`href="${href}"`))
  const blocked = header({ session: { authenticated: true, user: { role: 'unknown' } } })
  assert(blocked.includes('로그아웃') && !blocked.includes('운영진 메뉴'))
})

test('operator branding stays in the workspace and busy logout prevents duplicate submission', () => {
  const html = header({ session: { authenticated: true, user: { role: 'user' } }, signOutBusy: true })
  assert.match(html, /button class="header-signout" disabled="">로그아웃 중/)
  const footer = renderToStaticMarkup(React.createElement(SiteFooter, { operator: true }))
  assert(footer.includes('href="#/workspace"') && footer.includes('AI가 생성한 답변'))
  assert(!footer.includes('사진 출처') && !footer.includes('href="#/home"'))
})
