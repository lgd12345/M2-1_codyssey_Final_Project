import test from 'node:test'
import assert from 'node:assert/strict'
import { parseRecipients, departmentChange, isValidKey } from './domain/departments.js'
import { parseRoute, VIEW_OF_ROUTE } from './navigation.js'

test('recipients are read one per line or comma separated, trimmed, lower-cased and de-duplicated', () => {
  assert.deepEqual(parseRecipients(' A@Example.com,\nb@example.com\n\n a@example.com '), { list: ['a@example.com', 'b@example.com'], invalid: [] })
  assert.deepEqual(parseRecipients(''), { list: [], invalid: [] })
})

test('anything that is not an address is reported, never silently dropped', () => {
  assert.deepEqual(parseRecipients('ok@example.com, nope, a b@example.com'), { list: ['ok@example.com'], invalid: ['nope', 'a b@example.com'] })
})

test('only fields that really changed are sent', () => {
  const saved = { key: 'service', name: '서비스', description: '설명', recipients: ['a@example.com'], active: true }
  assert.deepEqual(departmentChange(saved, { name: '서비스', description: '설명', recipientsText: 'a@example.com', active: true }), {})
  assert.deepEqual(departmentChange(saved, { name: '현장 서비스', description: '설명', recipientsText: 'a@example.com\nb@example.com', active: false }),
    { name: '현장 서비스', recipients: ['a@example.com', 'b@example.com'], active: false })
})

test('department keys follow the server rule', () => {
  for (const ok of ['service', 'supplier_2', 'ab']) assert.ok(isValidKey(ok), ok)
  for (const bad of ['', 'A', '1abc', 'a b', 'a'.repeat(32), 'x/../y']) assert.ok(!isValidKey(bad), bad)
})

test('the department settings page is an operator screen', () => {
  assert.deepEqual(parseRoute('#/departments'), { name: 'departments' })
  assert.equal(VIEW_OF_ROUTE.departments, 'quality')
})
