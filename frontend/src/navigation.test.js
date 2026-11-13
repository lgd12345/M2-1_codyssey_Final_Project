import assert from 'node:assert/strict'
import test from 'node:test'
import { HOME, VIEW_OF_ROUTE, caseHref, parseRoute, portalHref, workHref } from './navigation.js'

test('빈 해시와 #/cases는 담당자 대기열이다', () => {
  assert.deepEqual(parseRoute(''), { name: 'list' })
  assert.deepEqual(parseRoute('#'), { name: 'list' })
  assert.deepEqual(parseRoute('#/cases'), { name: 'list' })
})

test('새 요청과 요청 상세를 구분한다', () => {
  assert.deepEqual(parseRoute('#/cases/new'), { name: 'new' })
  assert.deepEqual(parseRoute('#/cases/CLM-012'), { name: 'detail', id: 'CLM-012' })
  assert.equal(caseHref('CLM-012'), '#/cases/CLM-012')
})

test('고객 포털과 부서 업무함 경로를 구분한다', () => {
  assert.deepEqual(parseRoute('#/portal'), { name: 'portal-list' })
  assert.deepEqual(parseRoute('#/portal/new'), { name: 'portal-new' })
  assert.deepEqual(parseRoute('#/portal/CLM-003'), { name: 'portal-detail', id: 'CLM-003' })
  assert.deepEqual(parseRoute('#/work'), { name: 'work-list' })
  assert.deepEqual(parseRoute('#/work/SVC-001'), { name: 'work-detail', workKey: 'SVC-001' })
  assert.equal(portalHref('CLM-003'), '#/portal/CLM-003')
  assert.equal(workHref('SVC-001'), '#/work/SVC-001')
})

test('모든 화면은 어느 역할의 것인지 정해져 있고 역할마다 홈이 있다', () => {
  assert.equal(VIEW_OF_ROUTE[parseRoute('#/cases/CLM-001').name], 'quality')
  assert.equal(VIEW_OF_ROUTE[parseRoute('#/portal/new').name], 'customer')
  assert.equal(VIEW_OF_ROUTE[parseRoute('#/work/SAL-001').name], 'dept')
  assert.deepEqual(HOME, { quality: '#/cases', customer: '#/portal', dept: '#/work' })
})

test('알 수 없는 경로나 형식이 다른 번호는 notfound다', () => {
  assert.deepEqual(parseRoute('#/home'), { name: 'notfound' })
  assert.deepEqual(parseRoute('#/cases/abc'), { name: 'notfound' })
  assert.deepEqual(parseRoute('#/cases/CLM-1/extra'), { name: 'notfound' })
  assert.deepEqual(parseRoute('#/work/sv-1'), { name: 'notfound' })
})
