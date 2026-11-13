import assert from 'node:assert/strict'
import test from 'node:test'
import { HOME, VIEW_OF_ROUTE, caseHref, homeForRole, isStaff, parseRoute, portalHref, workHref } from './navigation.js'

test('빈 해시는 root이고 공개 화면은 각각 구분된다', () => {
  assert.deepEqual(parseRoute(''), { name: 'root' })
  assert.deepEqual(parseRoute('#'), { name: 'root' })
  assert.deepEqual(parseRoute('#/home'), { name: 'home' })
  assert.deepEqual(parseRoute('#/support'), { name: 'support' })
  assert.deepEqual(parseRoute('#/login'), { name: 'login' })
})

test('공개 화면은 어느 역할에도 속하지 않는다', () => {
  for (const hash of ['#/home', '#/support', '#/login']) assert.equal(VIEW_OF_ROUTE[parseRoute(hash).name], undefined)
})

test('담당자 대기열, 새 요청, 요청 상세를 구분한다', () => {
  assert.deepEqual(parseRoute('#/cases'), { name: 'list' })
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

test('주소 질의는 화면만 구분하고 고객사 소속을 결정하지 않는다', () => {
  assert.deepEqual(parseRoute('#/portal?company=forged'), { name: 'portal-list' })
  assert.deepEqual(parseRoute('#/cases/CLM-1000'), { name: 'detail', id: 'CLM-1000' })
})

test('로그인 후 화면은 역할에 속하고, 계정 역할마다 처음 가는 화면이 있다', () => {
  assert.equal(VIEW_OF_ROUTE[parseRoute('#/cases/CLM-001').name], 'quality')
  assert.equal(VIEW_OF_ROUTE[parseRoute('#/portal/new').name], 'customer')
  assert.equal(VIEW_OF_ROUTE[parseRoute('#/work/SAL-001').name], 'dept')
  assert.deepEqual(HOME, { quality: '#/cases', customer: '#/portal', dept: '#/work' })
  assert.equal(homeForRole('admin'), '#/cases')
  assert.equal(homeForRole('user'), '#/portal')
  assert.equal(homeForRole('customer'), '#/portal')
  assert.deepEqual(['admin', 'user', 'customer', undefined].map(isStaff), [true, false, false, false])
})

test('알 수 없는 경로나 형식이 다른 번호는 notfound다', () => {
  assert.deepEqual(parseRoute('#/unknown'), { name: 'notfound' })
  assert.deepEqual(parseRoute('#/cases/abc'), { name: 'notfound' })
  assert.deepEqual(parseRoute('#/cases/CLM-1/extra'), { name: 'notfound' })
  assert.deepEqual(parseRoute('#/work/sv-1'), { name: 'notfound' })
})
