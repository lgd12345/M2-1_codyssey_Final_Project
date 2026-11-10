import test from 'node:test'
import assert from 'node:assert/strict'
import { accountArea, needsSession, pageFromHash } from './navigation.js'

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
test('public information pages do not depend on an authentication/database request', () => {
  for (const page of ['home', 'support', 'register', 'guest']) assert.equal(needsSession(page), false)
  assert.equal(needsSession('login'), true)
  assert.equal(needsSession('workspace'), true)
  assert.equal(needsSession('companies'), true)
})

test('customer identities never enter the operator workspace; unknown roles fail closed', () => {
  assert.equal(accountArea({ role: 'customer' }), 'customer')
  for (const role of ['admin', 'user']) assert.equal(accountArea({ role }), 'operator')
  for (const user of [null, {}, { role: 'operator' }, { role: 'administrator' }]) assert.equal(accountArea(user), 'blocked')
})
