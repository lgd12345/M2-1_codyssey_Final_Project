import assert from 'node:assert/strict'
import test from 'node:test'
import { caseHref, parseRoute } from './navigation.js'

test('빈 해시와 #/cases는 접수 목록이다', () => {
  assert.deepEqual(parseRoute(''), { name: 'list' })
  assert.deepEqual(parseRoute('#'), { name: 'list' })
  assert.deepEqual(parseRoute('#/cases'), { name: 'list' })
})

test('새 요청과 요청 상세를 구분한다', () => {
  assert.deepEqual(parseRoute('#/cases/new'), { name: 'new' })
  assert.deepEqual(parseRoute('#/cases/CLM-012'), { name: 'detail', id: 'CLM-012' })
  assert.equal(caseHref('CLM-012'), '#/cases/CLM-012')
})

test('알 수 없는 경로나 형식이 다른 번호는 notfound다', () => {
  assert.deepEqual(parseRoute('#/home'), { name: 'notfound' })
  assert.deepEqual(parseRoute('#/cases/abc'), { name: 'notfound' })
  assert.deepEqual(parseRoute('#/cases/CLM-1/extra'), { name: 'notfound' })
})
