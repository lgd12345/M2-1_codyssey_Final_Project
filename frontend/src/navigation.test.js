import test from 'node:test'
import assert from 'node:assert/strict'
import { accountArea, needsSession, pageFromHash, pageForSession } from './navigation.js'

test('first visits and malformed routes safely show the public home', () => {
  for (const hash of ['', '#', '#/not-found', '#/https://example.org', '#/login?next=https://example.org']) assert.equal(pageFromHash(hash), 'home')
})
test('supported deep links resolve without requiring server rewrite rules', () => {
  for (const page of ['home', 'support', 'login', 'register', 'guest', 'workspace', 'companies']) assert.equal(pageFromHash(`#/${page}`), page)
})
test('native skip anchors preserve the current page; machine intro returns home', () => {
  assert.equal(pageFromHash('#main-content', 'login'), 'login')
  assert.equal(pageFromHash('#machines', 'login'), 'home')
})
test('public information pages do not require an authenticated session', () => {
  for (const page of ['home', 'support', 'register', 'guest']) assert.equal(needsSession(page), false)
  assert.equal(needsSession('login'), true)
  assert.equal(needsSession('workspace'), true)
  assert.equal(needsSession('companies'), true)
})

test('operators stay in their two workspaces even with public or login deep links', () => {
  for (const role of ['admin', 'user']) {
    const session = { authenticated: true, user: { role } }
    for (const page of ['home', 'support', 'login', 'register', 'guest', 'workspace']) assert.equal(pageForSession(page, session), 'workspace')
    assert.equal(pageForSession('companies', session), 'companies')
  }
})

test('signed-in customers avoid signup/login/operator routes while retaining customer information', () => {
  const session = { authenticated: true, user: { role: 'customer' } }
  for (const page of ['companies', 'login', 'register', 'guest', 'workspace']) assert.equal(pageForSession(page, session), 'workspace')
  for (const page of ['home', 'support']) assert.equal(pageForSession(page, session), page)
})

test('anonymous navigation is preserved and unknown signed-in roles fail closed', () => {
  for (const page of ['home', 'support', 'login', 'register', 'guest', 'workspace', 'companies']) {
    for (const session of [null, { authenticated: false }]) assert.equal(pageForSession(page, session), page)
    assert.equal(pageForSession(page, { authenticated: true, user: { role: 'unknown' } }), 'workspace')
  }
})

test('customer identities never enter the operator workspace; unknown roles fail closed', () => {
  assert.equal(accountArea({ role: 'customer' }), 'customer')
  for (const role of ['admin', 'user']) assert.equal(accountArea({ role }), 'operator')
  for (const user of [null, {}, { role: 'operator' }, { role: 'administrator' }]) assert.equal(accountArea(user), 'blocked')
})
