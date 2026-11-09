import test from 'node:test'
import assert from 'node:assert/strict'
import { needsSession, pageFromHash } from './navigation.js'

test('first visits and malformed routes safely show the public home', () => {
  for (const hash of ['', '#', '#/not-found', '#/https://example.org', '#/login?next=https://example.org']) assert.equal(pageFromHash(hash), 'home')
})
test('supported deep links resolve without requiring server rewrite rules', () => {
  for (const page of ['home', 'support', 'login', 'register', 'guest', 'workspace']) assert.equal(pageFromHash(`#/${page}`), page)
})
test('native skip anchors preserve the current page; machine intro returns home', () => {
  assert.equal(pageFromHash('#main-content', 'login'), 'login')
  assert.equal(pageFromHash('#machines', 'login'), 'home')
})
test('public information pages do not depend on an authentication/database request', () => {
  for (const page of ['home', 'support', 'register', 'guest']) assert.equal(needsSession(page), false)
  assert.equal(needsSession('login'), true)
  assert.equal(needsSession('workspace'), true)
})
