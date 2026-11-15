import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'

const base = '/api/v1/service-requests'
const marker = `[LIVE-E2E:${process.env.LIVE_E2E_RUN_TAG}]`
const retiredFields = ['comments', 'guides', 'approval', 'assignee', 'linked']

async function login(page, who) {
  await page.goto('/#/login')
  await page.getByLabel('아이디 또는 이메일', { exact: true }).fill(who)
  await page.getByLabel('비밀번호', { exact: true }).fill(process.env[`LIVE_E2E_${who === 'admin' ? 'ADMIN' : 'USER'}_PASSWORD`])
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await expect(page).toHaveURL(who === 'admin' ? /#\/cases$/ : /#\/portal$/)
  const auth = await (await page.request.get('/api/v1/auth/me')).json()
  expect(auth.authenticated).toBe(true)
  expect(auth.user.id).toBe(process.env[`LIVE_E2E_EXPECTED_${who === 'admin' ? 'ADMIN' : 'USER'}_ID`])
  expect(auth.user.role).toBe(who === 'admin' ? 'admin' : 'user')
}

const headers = async page => ({ Origin: new URL(page.url()).origin,
  'X-CSRF-Token': (await (await page.request.get('/api/v1/auth/me')).json()).csrf_token })
const stored = async (page, id) => (await (await page.request.get(`${base}/${id}`)).json())

async function prepareForm(page, message) {
  await page.getByRole('combobox', { name: '접수 사유 *', exact: true }).selectOption('알람·전장 이상')
  const context = await (await page.request.get(`${base}/context`)).json()
  const model = context.equipment.find(e => e.id === process.env.LIVE_E2E_USER_EQUIPMENT_ID)
  expect(model).toBeTruthy()
  await page.getByRole('combobox', { name: '기종 *', exact: true }).fill(model.machine)
  await page.getByRole('listbox', { name: '기종 목록', exact: true }).getByRole('option', { name: model.machine, exact: true }).click()
  await page.getByLabel('메시지 *', { exact: true }).fill(message)
  await expect(page.locator('input[type=file]')).toHaveCount(0)
}

async function submit(page) {
  const response = page.waitForResponse(r => r.url().endsWith(base) && r.request().method() === 'POST')
  await page.getByRole('button', { name: '전송', exact: true }).click()
  const saved = await response
  expect(saved.status()).toBe(201)
  const item = await saved.json()
  expect(item.status).toBe('접수됨')
  await expect(page).toHaveURL(new RegExp(`/(portal|cases)/${item.id}$`))
  return item
}

async function sessions(browser, run) {
  const uc = await browser.newContext(), ac = await browser.newContext()
  const user = await uc.newPage(), admin = await ac.newPage()
  const errors = []
  for (const page of [user, admin]) page.on('pageerror', e => errors.push(e.message))
  try {
    await login(user, 'user'); await login(admin, 'admin')
    await run(user, admin, uc)
    expect(errors).toEqual([])
  } finally { await uc.close(); await ac.close() }
}

async function openRequest(user, message) {
  await user.goto('/#/portal/new'); await prepareForm(user, `${marker} ${message}`)
  return submit(user)
}

async function analyse(admin, id) {
  await admin.goto(`/#/cases/${id}`)
  await admin.getByRole('button', { name: '분석 시작', exact: true }).click()
  await expect.poll(async () => (await stored(admin, id)).analysisRun?.status,
    { timeout: 270000, intervals: [3000] }).toMatch(/^(succeeded|failed)$/)
  const item = await stored(admin, id)
  expect(item.status).toBe('처리 중')
  expect(item.analysisRun).toEqual({ status: 'succeeded', errorCode: null })
  expect(['answered', 'insufficient_evidence']).toContain(item.analysis.status)
  expect(item.analysis.summary.length).toBeGreaterThan(5)
  for (const field of retiredFields) expect(item).not.toHaveProperty(field)
  const ids = item.analysis.evidence.map(e => e.id)
  expect(new Set(ids).size).toBe(ids.length)
  for (const cause of item.analysis.causes) {
    expect(cause.evidence.length).toBeGreaterThan(0)
    for (const id of cause.evidence) expect(ids).toContain(id)
  }
  if (item.analysis.status === 'answered') {
    expect(item.analysis.evidence.length).toBeGreaterThan(0)
    for (const e of item.analysis.evidence) {
      expect(['fsr', 'manual']).toContain(e.kind)
      expect(e.excerpt.length).toBeGreaterThan(0)
    }
  }
  await admin.reload()
  await expect(admin.getByText(item.analysis.summary.slice(0, 20), { exact: false }).first()).toBeVisible()
  return item
}

test('current database: durable shared-model intake, network recovery, real auth and company isolation', async ({ browser }) => {
  await sessions(browser, async (user, admin, uc) => {
    await user.goto('/#/portal/new'); await prepareForm(user, `${marker} 재시도 접수 검증`)
    await uc.setOffline(true)
    await user.getByRole('button', { name: '전송', exact: true }).click()
    await expect(user.getByRole('alert')).toHaveText('서버에 연결하지 못했습니다.')
    await expect(user.getByLabel('메시지 *', { exact: true })).not.toBeEmpty()
    await uc.setOffline(false)
    const own = await submit(user)
    await user.reload(); await expect(user.locator('.pd-desc')).toContainText(marker)
    for (const field of [...retiredFields, 'analysis', 'departments']) expect(own).not.toHaveProperty(field)
    await admin.goto(`/#/cases/${own.id}`)
    await expect(admin.getByText('아직 분석 결과가 없습니다.', { exact: false })).toBeVisible()
    const a = await (await admin.request.get(`${base}/context`)).json()
    const u = await (await user.request.get(`${base}/context`)).json()
    expect(a.equipment.map(e => e.id).sort()).toEqual(u.equipment.map(e => e.id).sort())
    const foreign = process.env.LIVE_E2E_FOREIGN_REQUEST_ID
    expect((await admin.request.get(`${base}/${foreign}`)).status()).toBe(200)
    expect((await user.request.get(`${base}/${foreign}`)).status()).toBe(404)
    await user.goto('/#/portal?company=forged-company')
    const list = (await (await user.request.get(base)).json()).requests
    expect(list.some(r => r.id === own.id)).toBe(true)
    expect(list.some(r => r.id === foreign)).toBe(false)
    const payload = { equipment_id: randomUUID(), reason: '알람·전장 이상', message: `${marker} unknown model` }
    expect((await user.request.post(base, { headers: await headers(user), data: payload })).status()).toBe(404)
    expect((await user.request.post(base, { headers: { Origin: new URL(user.url()).origin }, data: payload })).status()).toBe(403)
    expect((await user.request.post(base, { headers: { ...await headers(user), Origin: 'https://untrusted.example' }, data: payload })).status()).toBe(403)
    for (const page of [user, admin]) {
      await page.getByRole('button', { name: '로그아웃', exact: true }).click()
      await expect(page).toHaveURL(/#\/home$/)
      expect((await (await page.request.get('/api/v1/auth/me')).json()).authenticated).toBe(false)
      expect((await page.request.get(base)).status()).toBe(401)
    }
  })
})

test('current database: real analysis, optional inline template, direct closure and customer result only', async ({ browser }) => {
  test.setTimeout(480000)
  await sessions(browser, async (user, admin) => {
    const own = await openRequest(user, '가상 시험: ATC 공구 교환 중 암이 멈추고 알람 2023이 발생합니다. 현장 작업은 하지 않았습니다.')
    const item = await analyse(admin, own.id)
    const customer = await stored(user, own.id)
    expect(customer.status).toBe('처리 중')
    for (const field of ['analysis', 'departments', ...retiredFields]) expect(customer).not.toHaveProperty(field)
    if (item.departments.some(d => d.aiSelected)) {
      const before = item.mailDrafts.length
      await admin.getByRole('button', { name: '메일 작성', exact: true }).first().click()
      await expect(admin.getByLabel('메일 제목', { exact: true }).first()).not.toBeEmpty()
      expect((await stored(admin, own.id)).mailDrafts.length).toBe(before)
      await admin.getByRole('button', { name: '접기', exact: true }).first().click()
    }
    const note = `${marker} 가상 기능 검증 종결. 실제 수리나 부서 메일 발송은 수행하지 않았습니다.`
    await admin.getByLabel('처리 결과 (고객에게 보입니다)', { exact: true }).fill(note)
    await admin.getByRole('button', { name: '요청 종결', exact: true }).click()
    await expect(admin.getByText('종결됨', { exact: true })).toBeVisible()
    await user.goto(`/#/portal/${own.id}`)
    await expect(user.getByText(note, { exact: true })).toBeVisible()
    await expect(user.getByRole('heading', { name: '요청 이력', exact: true })).toBeVisible()
    await expect(user.getByRole('button', { name: '원본 페이지 보기', exact: true })).toHaveCount(0)
    const done = await stored(user, own.id)
    expect(done.status).toBe('완료')
    for (const field of [...retiredFields, 'analysis', 'departments']) expect(done).not.toHaveProperty(field)
    expect((await user.request.get(`${base}/${own.id}/evidence/E1/page`)).status()).toBe(403)
    console.log(JSON.stringify({ real_llm: true, request: own.id, status: item.analysis.status, closure: true, department_mail_sent: false }))
  })
})

test('current database: retired notes, replies, assignment and work cannot be used through APIs', async ({ browser }) => {
  await sessions(browser, async (user, admin) => {
    const own = await openRequest(user, '폐기 API 차단 검증')
    for (const page of [user, admin]) {
      for (const action of ['comments', 'approval', 'decline', 'assignee', 'replies', 'callback', 'close-request', 'work/SVC-001/start']) {
        const r = await page.request.post(`${base}/${own.id}/${action}`, { headers: await headers(page), data: { kind: 'public', text: 'x' } })
        expect([404, 405], action).toContain(r.status())
      }
    }
    for (const action of ['analysis', 'reanalysis', 'resolution', 'additional-info']) {
      expect((await user.request.post(`${base}/${own.id}/${action}`, { headers: await headers(user), data: { note: 'x', text: 'x' } })).status()).toBe(403)
    }
    for (const field of retiredFields) expect(await stored(user, own.id)).not.toHaveProperty(field)
    for (const name of ['정보 추가', '콜백 요청', '종결 요청', '내부 메모 추가', '고객에게 답변']) {
      await expect(user.getByRole('button', { name, exact: true })).toHaveCount(0)
    }
  })
})

test('current database: real-model quality on current analysis screens', async ({ browser }) => {
  test.setTimeout(900000)
  await sessions(browser, async (user, admin) => {
    const symptom = await analyse(admin, (await openRequest(user, 'Y축 원점 복귀를 하면 O.T 알람이 뜨고 원점이 잡히지 않습니다. 슬라이드 커버 쪽에 절삭유가 샌 흔적이 있습니다.')).id)
    expect(symptom.analysis.status).toBe('answered')
    await expect(admin.getByRole('heading', { name: '원인 후보', exact: true })).toBeVisible()
    expect(await admin.locator('ol.causes > li').count()).toBe(symptom.analysis.causes.length)
    for (const [kind, label] of [['fsr', '과거 사례'], ['manual', '관련 문서']]) {
      const count = symptom.analysis.evidence.filter(e => e.kind === kind).length
      if (count) {
        const group = admin.locator('details').filter({ has: admin.locator('summary').filter({ hasText: label }) })
        await group.locator('summary').click()
        expect(await group.locator('ul.evidence > li').count()).toBe(count)
      }
    }
    const identifiers = /FSR-\d{5}|\b\d{4}-\d{2}-\d{3}-\d{2}\b/g
    const known = [symptom.intake.symptom, ...symptom.analysis.evidence.map(e => `${e.title} ${e.source} ${e.excerpt}`)].join(' ')
    for (const id of (await admin.locator('main').innerText()).match(identifiers) ?? []) expect(known).toContain(id)
    const offtopic = await analyse(admin, (await openRequest(user, '오늘 점심 메뉴를 추천해 주세요. 김치찌개가 좋을까요?')).id)
    expect(offtopic.analysis.status).toBe('insufficient_evidence')
    expect(offtopic.analysis.causes).toEqual([])
    expect(offtopic.departments.every(d => !d.aiSelected)).toBe(true)
    expect((await stored(user, offtopic.id)).status).toBe('처리 중')
    await expect(admin.getByRole('button', { name: '메일 작성', exact: true })).toHaveCount(0)
    const part = await analyse(admin, (await openRequest(user, '부품 번호 2064-75-114-00이 어떤 부품인지 어느 기종 부품 목록에 있는지 알려 주세요.')).id)
    expect(part.analysis.status).toBe('answered')
    expect(part.analysis.parts.some(p => /2064-75-114-00/.test(p.name) && /COVER|커버/i.test(p.name))).toBe(true)
    expect(part.analysis.evidence.some(e => /PARTS LIST/i.test(e.title) && /PL-147/.test(e.source))).toBe(true)
    await expect(admin.getByText('2064-75-114-00', { exact: false }).first()).toBeVisible()
    if (process.env.LIVE_E2E_SCREENSHOT) await admin.screenshot({ path: process.env.LIVE_E2E_SCREENSHOT, fullPage: true })
  })
})
