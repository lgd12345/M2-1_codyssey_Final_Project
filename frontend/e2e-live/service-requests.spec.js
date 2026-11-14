import { test, expect } from '@playwright/test'

const base = '/api/v1/service-requests'
const marker = `[LIVE-E2E:${process.env.LIVE_E2E_RUN_TAG}]`
const DEPARTMENT_NAME = { service: '서비스', quality: '품질', parts: '부품·자재', sales: '영업' }

async function login(page, loginId, password, expectedId, role) {
  await page.goto('/#/login')
  await page.getByLabel('아이디 또는 이메일', { exact: true }).fill(loginId)
  await page.getByLabel('비밀번호', { exact: true }).fill(password)
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/v1/auth/login') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)
  const auth = await response.json()
  expect(auth.authenticated).toBe(true)
  expect(auth.user.id).toBe(expectedId) // Must match identities read from the approved DB.
  expect(auth.user.role).toBe(role)
}

async function prepareForm(page, equipmentId, message) {
  await page.getByRole('combobox', { name: '접수 사유 *', exact: true }).selectOption('기술 문의')
  await page.getByRole('combobox', { name: '기계 · 호기 *', exact: true }).selectOption(equipmentId)
  await page.getByLabel('메시지 *', { exact: true }).fill(message)
  await expect(page.locator('input[type=file]')).toBeDisabled()
  await page.getByRole('button', { name: '계속', exact: true }).click()
  await page.getByLabel('이름 *', { exact: true }).fill('E2E 검증 담당자')
  await page.getByLabel('전화번호 *', { exact: true }).fill('010-0000-0000')
}

async function submit(page) {
  const result = page.waitForResponse(response => response.url().endsWith(base) && response.request().method() === 'POST')
  await page.getByRole('button', { name: '전송', exact: true }).click()
  const response = await result
  expect(response.status()).toBe(201)
  const item = await response.json()
  expect(item.id).toMatch(/^CLM-\d+$/)
  expect(item.status).toBe('접수됨')
  return item
}

const csrfHeaders = async page => ({
  Origin: new URL(page.url()).origin,
  'X-CSRF-Token': (await (await page.request.get('/api/v1/auth/me')).json()).csrf_token,
})

test('current database: user intake, admin review and cross-company isolation', async ({ browser }) => {
  const errors = []
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const user = await userContext.newPage()
  const admin = await adminContext.newPage()
  user.on('pageerror', error => errors.push(error.message))
  admin.on('pageerror', error => errors.push(error.message))
  try {
    await login(user, 'user', process.env.LIVE_E2E_USER_PASSWORD, process.env.LIVE_E2E_EXPECTED_USER_ID, 'user')
    await expect(user).toHaveURL(/#\/portal$/)
    await expect(user.getByRole('heading', { name: '내 서비스 요청', exact: true })).toBeVisible()
    const contextResponse = await user.request.get(`${base}/context`)
    expect(contextResponse.status()).toBe(200)
    const context = await contextResponse.json()
    expect(context.company).not.toBeNull()
    expect(context.equipment.map(item => item.id)).toContain(process.env.LIVE_E2E_USER_EQUIPMENT_ID)
    expect(context.equipment.map(item => item.id)).not.toContain(process.env.LIVE_E2E_OTHER_EQUIPMENT_ID)

    await user.getByRole('link', { name: '새 서비스 요청', exact: true }).click()
    await prepareForm(user, process.env.LIVE_E2E_USER_EQUIPMENT_ID, `${marker} user 현재 DB 접수 검증`)
    await userContext.setOffline(true)
    await user.getByRole('button', { name: '전송', exact: true }).click()
    await expect(user.getByRole('alert')).toHaveText('서버에 연결하지 못했습니다.')
    await expect(user).toHaveURL(/#\/portal\/new$/)
    await expect(user.getByLabel('이름 *', { exact: true })).toHaveValue('E2E 검증 담당자')
    await userContext.setOffline(false)
    const beforeSave = await user.request.get(base)
    expect((await beforeSave.json()).requests.filter(item => item.intake.symptom.startsWith(marker))).toHaveLength(0)

    const own = await submit(user)
    expect(own).not.toHaveProperty('analysis')
    expect(own).not.toHaveProperty('departments')
    expect(own).not.toHaveProperty('approval')
    await expect(user).toHaveURL(new RegExp(`#/portal/${own.id}$`))
    await expect(user.locator('.pd-desc')).toContainText(marker)
    await user.reload()
    await expect(user.locator('.pd-desc')).toContainText(marker)
    await expect(user.getByRole('button', { name: '콜백 요청', exact: true })).toBeEnabled()

    await login(admin, 'admin', process.env.LIVE_E2E_ADMIN_PASSWORD, process.env.LIVE_E2E_EXPECTED_ADMIN_ID, 'admin')
    await expect(admin).toHaveURL(/#\/cases$/)
    await admin.getByRole('link', { name: own.id, exact: true }).click()
    await expect(admin.getByRole('heading', { name: own.title, exact: true })).toBeVisible()
    await expect(admin.getByText('아직 분석 결과가 없습니다.', { exact: false })).toBeVisible()
    await expect(admin.getByRole('button', { name: '나에게 지정', exact: true })).toBeEnabled()
    await expect(admin.getByRole('button', { name: '내부 메모 추가', exact: true })).toBeEnabled()
    await expect(admin.locator('.timeline')).toHaveCount(0)
    const stored = await admin.request.get(`${base}/${own.id}`)
    expect(stored.status()).toBe(200)
    expect((await stored.json()).analysis).toBeNull()
    await admin.reload()
    await expect(admin.getByRole('heading', { name: own.title, exact: true })).toBeVisible()

    // Admin can create for another company; the real user must not read/use it.
    await admin.goto('/#/cases/new')
    await prepareForm(admin, process.env.LIVE_E2E_OTHER_EQUIPMENT_ID, `${marker} admin 타사 접근제한 검증`)
    const other = await submit(admin)
    await expect(admin).toHaveURL(new RegExp(`#/cases/${other.id}$`))
    const denied = await user.request.get(`${base}/${other.id}`)
    expect(denied.status()).toBe(404)
    await user.goto('/#/portal?company=forged-company')
    await expect(user.getByRole('link', { name: own.id, exact: true })).toBeVisible()
    await expect(user.getByRole('link', { name: other.id, exact: true })).toHaveCount(0)

    const me = await user.request.get('/api/v1/auth/me')
    const session = await me.json()
    const payload = {
      equipment_id: process.env.LIVE_E2E_OTHER_EQUIPMENT_ID,
      reason: '기술 문의', message: `${marker} denied submission`,
      contact: { name: 'E2E 검증 담당자', phone: '010-0000-0000' },
    }
    const origin = new URL(user.url()).origin
    const forged = await user.request.post(base, { data: payload, headers: { Origin: origin, 'X-CSRF-Token': session.csrf_token } })
    expect(forged.status()).toBe(404)
    const noCsrf = await user.request.post(base, { data: payload, headers: { Origin: origin } })
    expect(noCsrf.status()).toBe(403)
    expect((await noCsrf.json()).code).toBe('BAD_CSRF')
    const wrongOrigin = await user.request.post(base, { data: payload, headers: { Origin: 'https://untrusted.example', 'X-CSRF-Token': session.csrf_token } })
    expect(wrongOrigin.status()).toBe(403)
    expect((await wrongOrigin.json()).code).toBe('BAD_ORIGIN')

    const visible = await user.request.get(base)
    const visibleItems = (await visible.json()).requests
    expect(visibleItems.some(item => item.id === own.id)).toBe(true)
    expect(visibleItems.some(item => item.id === other.id)).toBe(false)
    const all = await admin.request.get(base)
    const created = (await all.json()).requests.filter(item => item.intake.symptom.startsWith(marker))
    expect(created.map(item => item.id).sort()).toEqual([own.id, other.id].sort())
    expect(created.every(item => item.status === '접수됨')).toBe(true)
    console.log(JSON.stringify({ database: 'service_poc_test', user_request: own.id, admin_request: other.id,
      real_auth: true, persisted_after_reload: true, company_isolation: true, csrf_and_origin_enforced: true }))

    for (const page of [user, admin]) {
      await page.getByRole('button', { name: '로그아웃', exact: true }).click()
      await expect(page).toHaveURL(/#\/home$/)
      const loggedOut = await page.request.get('/api/v1/auth/me')
      expect((await loggedOut.json()).authenticated).toBe(false)
    }
    const anonymous = await user.request.get(base)
    expect(anonymous.status()).toBe(401)
    expect(errors).toEqual([])
  } finally {
    await userContext.close()
    await adminContext.close()
  }
})

// Calls the REAL configured LLM and the real Qwen/Postgres retrieval, then drives the whole review,
// approval, department work and closure on that real analysis. Assertions are structural and
// grounded-ness based because model wording varies; it does not pin specific model prose.
test('current database: real AI analysis, approval, department work and closure', async ({ browser }) => {
  test.setTimeout(480000)
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const user = await userContext.newPage()
  const admin = await adminContext.newPage()
  try {
    await login(user, 'user', process.env.LIVE_E2E_USER_PASSWORD, process.env.LIVE_E2E_EXPECTED_USER_ID, 'user')
    await user.getByRole('link', { name: '새 서비스 요청', exact: true }).click()
    await prepareForm(user, process.env.LIVE_E2E_USER_EQUIPMENT_ID, `${marker} ATC 공구 교환 중 암이 멈추고 알람 2023 이 발생합니다.`)
    const own = await submit(user)

    await login(admin, 'admin', process.env.LIVE_E2E_ADMIN_PASSWORD, process.env.LIVE_E2E_EXPECTED_ADMIN_ID, 'admin')
    await admin.goto(`/#/cases/${own.id}`)
    await expect(admin.getByRole('heading', { name: own.title, exact: true })).toBeVisible()
    const started = Date.now()
    await admin.getByRole('button', { name: 'AI 분석 시작', exact: true }).click()
    await expect(admin.getByText('분석 중입니다.', { exact: false })).toBeVisible()
    await expect(admin.getByRole('button', { name: 'AI 분석 시작', exact: true })).toHaveCount(0)
    await expect.poll(async () => (await (await admin.request.get(`${base}/${own.id}`)).json()).status,
      { timeout: 270000, intervals: [3000] }).not.toBe('분석 중')
    const seconds = Math.round((Date.now() - started) / 1000)
    const stored = await (await admin.request.get(`${base}/${own.id}`)).json()
    expect(stored.analysisRun, 'analysis must succeed against the real model: ' + JSON.stringify(stored.analysisRun)).toEqual({ status: 'succeeded', errorCode: null })
    const analysis = stored.analysis
    expect(['answered', 'insufficient_evidence']).toContain(analysis.status)
    expect(stored.status).toBe(analysis.status === 'answered' ? '검토 대기' : '추가 정보 필요')
    expect(analysis.summary.length).toBeGreaterThan(5)
    const ids = analysis.evidence.map(item => item.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const cause of analysis.causes) {
      expect(cause.evidence.length).toBeGreaterThan(0)
      for (const id of cause.evidence) expect(ids).toContain(id)
    }
    if (analysis.status === 'answered') {
      expect(analysis.evidence.length).toBeGreaterThan(0)
      for (const item of analysis.evidence) {
        expect(item.excerpt.length, 'excerpt must come from stored source: ' + item.source).toBeGreaterThan(0)
        expect(['fsr', 'manual']).toContain(item.kind)
      }
    }
    expect(stored.departments.map(item => item.key)).toEqual(['service', 'quality', 'parts', 'sales'])
    expect(stored.linked).toEqual([])
    expect(stored.approval).toBeNull()
    await admin.reload()
    await expect(admin.getByText(analysis.summary.slice(0, 20), { exact: false }).first()).toBeVisible()
    await admin.getByRole('tab', { name: '매뉴얼 열람', exact: true }).click()
    await admin.screenshot({ path: process.env.LIVE_E2E_SCREENSHOT || 'test-results/live-analysis.png', fullPage: true })

    const customerView = await (await user.request.get(`${base}/${own.id}`)).json()
    expect(customerView).not.toHaveProperty('analysis')
    expect(customerView).not.toHaveProperty('departments')
    expect(JSON.stringify(customerView)).not.toContain(analysis.summary)

    // ---- review, approval, department work, closure on the same real analysis ----
    if (stored.status === '추가 정보 필요') {
      // Honest path when the real model finds no evidence: the customer is asked and the flow stops here.
      expect((await (await user.request.get(`${base}/${own.id}`)).json()).status).toBe('정보 요청')
      console.log(JSON.stringify({ real_llm: true, request: own.id, seconds, status: analysis.status, workflow: 'stopped_for_customer_information' }))
      return
    }
    const recommended = stored.departments.filter(item => item.selected)
    if (recommended.length === 0) {
      await admin.getByRole('checkbox', { name: /서비스/ }).click()
      await expect(admin.getByRole('checkbox', { name: /서비스/ })).toBeChecked()
      await admin.getByLabel('서비스 초안', { exact: true }).fill(`${marker} 서비스 검토 지시`)
    } else {
      await admin.getByLabel(`${DEPARTMENT_NAME[recommended[0].key]} 초안`, { exact: true }).fill(`${marker} 검토자 수정 지시`)
    }
    await expect(admin.getByRole('button', { name: '승인', exact: true })).toBeEnabled({ timeout: 10000 })
    await admin.getByRole('button', { name: '승인', exact: true }).click()
    await expect(admin.getByRole('button', { name: /^처리 중/ })).toBeVisible()
    const approved = await (await admin.request.get(`${base}/${own.id}`)).json()
    expect(approved.status).toBe('처리 중')
    expect(approved.linked.length).toBeGreaterThan(0)
    expect(approved.linked.some(work => work.content.includes(marker))).toBe(true)
    expect(approved.linked.every(work => work.status === '전달됨' && work.result === null)).toBe(true)
    const numeric = own.id.slice(4)
    for (const work of approved.linked) expect(work.workKey).toMatch(new RegExp(`^(SVC|QLT|PRT|SAL)-${numeric}$`))
    const duplicate = await admin.request.post(`${base}/${own.id}/approval`, { headers: await csrfHeaders(admin) })
    expect(duplicate.status()).toBe(409)
    expect((await (await admin.request.get(`${base}/${own.id}`)).json()).linked.length).toBe(approved.linked.length)
    const customerAfterApproval = await (await user.request.get(`${base}/${own.id}`)).json()
    expect(customerAfterApproval.status).toBe('처리 중')
    expect(JSON.stringify(customerAfterApproval)).not.toContain(approved.linked[0].workKey)
    expect(customerAfterApproval).not.toHaveProperty('linked')
    for (const work of approved.linked) {
      await admin.goto(`/#/work/${work.workKey}`)
      await admin.getByRole('button', { name: '처리 시작', exact: true }).click()
      await admin.getByLabel('조치 내용 *', { exact: true }).fill(`${marker} ${work.workKey} 조치 완료`)
      await admin.getByRole('button', { name: '처리 완료', exact: true }).click()
      await expect(admin.getByText(`${work.workKey} 조치 완료`, { exact: false }).first()).toBeVisible()
    }
    await admin.goto(`/#/cases/${own.id}`)
    await admin.getByLabel('종결 메모(고객에게 보입니다)', { exact: true }).fill(`${marker} 결과를 안내드렸습니다.`)
    await admin.getByRole('button', { name: '요청 종결', exact: true }).click()
    await expect(admin.getByText('종결됨', { exact: true })).toBeVisible()
    const closed = await (await admin.request.get(`${base}/${own.id}`)).json()
    expect(closed.status).toBe('종결')
    expect(closed.linked.every(work => work.status === '완료' && work.result.summary.includes('조치 완료'))).toBe(true)
    await user.reload()
    await expect(user.getByText('이 서비스 요청은 완료되었습니다.', { exact: false })).toBeVisible()
    await expect(user.getByText('결과를 안내드렸습니다.', { exact: false })).toBeVisible()
    const customerClosed = await (await user.request.get(`${base}/${own.id}`)).json()
    expect(customerClosed.status).toBe('완료')
    for (const field of ['linked', 'approval', 'analysis', 'departments']) expect(customerClosed).not.toHaveProperty(field)
    console.log(JSON.stringify({ real_llm: true, request: own.id, closed_after_real_workflow: true, seconds,
      status: analysis.status, causes: analysis.causes.length, evidence: analysis.evidence.map(item => item.source),
      case_search: analysis.caseSearch, departments_delivered: approved.linked.map(work => work.key) }))
  } finally {
    await userContext.close()
    await adminContext.close()
  }
})

// No model call: operator/customer interaction rules on a real stored request in the current environment.
test('current database: customer actions, internal notes and company isolation on real data', async ({ browser }) => {
  test.setTimeout(120000)
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const user = await userContext.newPage()
  const admin = await adminContext.newPage()
  try {
    await login(user, 'user', process.env.LIVE_E2E_USER_PASSWORD, process.env.LIVE_E2E_EXPECTED_USER_ID, 'user')
    await user.getByRole('link', { name: '새 서비스 요청', exact: true }).click()
    await prepareForm(user, process.env.LIVE_E2E_USER_EQUIPMENT_ID, `${marker} 고객 조작 확인용 요청`)
    const own = await submit(user)
    await user.getByRole('button', { name: '콜백 요청', exact: true }).click()
    await user.getByRole('button', { name: '요청', exact: true }).click()
    await expect(user.getByText('콜백을 요청했습니다.', { exact: false }).first()).toBeVisible()
    await user.getByRole('button', { name: '종결 요청', exact: true }).click()
    await user.getByLabel('종결 사유 *', { exact: true }).fill(`${marker} 스스로 해결`)
    await user.getByRole('button', { name: '전송', exact: true }).click()
    await expect(user.getByText('종결을 요청했습니다.', { exact: false }).first()).toBeVisible()

    await login(admin, 'admin', process.env.LIVE_E2E_ADMIN_PASSWORD, process.env.LIVE_E2E_EXPECTED_ADMIN_ID, 'admin')
    await admin.goto(`/#/cases/${own.id}`)
    await expect(admin.getByText('고객이 종결을 요청했습니다.', { exact: false })).toBeVisible()
    await admin.getByRole('button', { name: '나에게 지정', exact: true }).click()
    await expect(admin.getByText('admin 담당자로 지정', { exact: false })).toBeVisible()
    await admin.getByRole('button', { name: '내부 메모 추가', exact: true }).click()
    await admin.getByLabel('내부 메모', { exact: true }).fill(`${marker} 내부전용 메모`)
    await admin.getByRole('button', { name: '저장', exact: true }).click()
    await expect(admin.getByText('내부전용 메모', { exact: false })).toBeVisible()
    await admin.getByRole('button', { name: '고객에게 답변', exact: true }).click()
    await admin.getByLabel('고객 답변', { exact: true }).fill(`${marker} 확인 후 연락드리겠습니다.`)
    await admin.getByRole('button', { name: '저장', exact: true }).click()
    await expect(admin.getByText('확인 후 연락드리겠습니다.', { exact: false }).first()).toBeVisible()

    await user.reload()
    await expect(user.getByText('확인 후 연락드리겠습니다.', { exact: false })).toBeVisible()
    const customerView = await (await user.request.get(`${base}/${own.id}`)).json()
    expect(JSON.stringify(customerView)).not.toContain('내부전용')
    expect(customerView.closeRequested).toBe(true)
    // Operator-only actions are refused for the real customer account even with valid session and CSRF.
    const headers = await csrfHeaders(user)
    for (const action of ['approval', 'assignee', 'reanalysis', 'analysis'])
      expect((await user.request.post(`${base}/${own.id}/${action}`, { headers })).status(), action).toBe(403)
    expect((await user.request.post(`${base}/${own.id}/comments`, { headers, data: { kind: 'internal', text: 'x' } })).status()).toBe(403)
    // Approval is impossible without an analysis, even for the real operator.
    expect((await admin.request.post(`${base}/${own.id}/approval`, { headers: await csrfHeaders(admin) })).status()).toBe(409)
    console.log(JSON.stringify({ customer_actions_and_internal_notes_isolated: true, request: own.id }))
  } finally {
    await userContext.close()
    await adminContext.close()
  }
})

// Real LLM, real retrieval, real screens: what an operator actually sees for three representative requests.
const analyse = async (admin, id) => {
  await admin.goto(`/#/cases/${id}`)
  await admin.getByRole('button', { name: 'AI 분석 시작', exact: true }).click()
  await expect(admin.getByText('분석 중입니다.', { exact: false })).toBeVisible()
  await expect.poll(async () => (await (await admin.request.get(`${base}/${id}`)).json()).status,
    { timeout: 270000, intervals: [3000] }).not.toBe('분석 중')
  const stored = await (await admin.request.get(`${base}/${id}`)).json()
  expect(stored.analysisRun, 'analysis must not fail').toEqual({ status: 'succeeded', errorCode: null })
  await admin.reload()
  return stored
}
const IDENTIFIERS = /FSR-\d{5}|\b\d{4}-\d{2}-\d{3}-\d{2}\b/g

test('current database: analysis quality as shown on the screens', async ({ browser }) => {
  test.setTimeout(900000)
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const user = await userContext.newPage()
  const admin = await adminContext.newPage()
  try {
    await login(user, 'user', process.env.LIVE_E2E_USER_PASSWORD, process.env.LIVE_E2E_EXPECTED_USER_ID, 'user')
    await login(admin, 'admin', process.env.LIVE_E2E_ADMIN_PASSWORD, process.env.LIVE_E2E_EXPECTED_ADMIN_ID, 'admin')
    const open = async message => {
      await user.goto('/#/portal/new')
      await prepareForm(user, process.env.LIVE_E2E_USER_EQUIPMENT_ID, message)
      return submit(user)
    }
    const report = {}

    // 1) A realistic symptom: grounded causes with sources, listed evidence, and nothing the evidence lacks.
    const symptomMessage = `${marker} Y축 원점 복귀를 하면 O.T 알람이 뜨고 원점이 잡히지 않습니다. 슬라이드 커버 쪽에 절삭유가 샌 흔적이 있습니다.`
    const symptom = await analyse(admin, (await open(symptomMessage)).id)
    expect(symptom.analysis.status).toBe('answered')
    await expect(admin.getByRole('heading', { name: '추정 원인', exact: true })).toBeVisible()
    const causeCount = await admin.locator('ol.causes > li').count()
    expect(causeCount).toBe(symptom.analysis.causes.length)
    expect(causeCount).toBeGreaterThan(0)
    for (const cause of symptom.analysis.causes) await expect(admin.getByText(cause.title, { exact: false }).first()).toBeVisible()
    expect(await admin.locator('ol.causes .source').count()).toBe(causeCount)
    await admin.getByRole('tab', { name: '과거 정비 이력', exact: true }).click()
    expect(await admin.locator('ul.evidence > li').count()).toBe(symptom.analysis.evidence.filter(item => item.kind === 'fsr').length)
    await admin.getByRole('tab', { name: '매뉴얼 열람', exact: true }).click()
    expect(await admin.locator('ul.evidence > li').count()).toBe(symptom.analysis.evidence.filter(item => item.kind === 'manual').length)
    const known = [symptomMessage, ...symptom.analysis.evidence.map(item => `${item.title} ${item.source} ${item.excerpt}`)].join(' ')
    const shown = (await admin.locator('main').innerText()).match(IDENTIFIERS) ?? []
    for (const identifier of shown) expect(known, `screen shows an identifier absent from request and evidence: ${identifier}`).toContain(identifier)
    report.symptom = { causes: causeCount, evidence: symptom.analysis.evidence.length, departments: symptom.departments.filter(d => d.selected).map(d => d.key) }

    // 2) An unrelated request: the screen must say there is no evidence and offer nothing to approve.
    const offtopic = await analyse(admin, (await open(`${marker} 오늘 점심 메뉴를 추천해 주세요. 김치찌개가 좋을까요?`)).id)
    expect(offtopic.analysis.status).toBe('insufficient_evidence')
    expect(offtopic.status).toBe('추가 정보 필요')
    await expect(admin.getByText('관련 근거가 부족해 원인 후보와 권장 사항을 제시하지 않았습니다.', { exact: false })).toBeVisible()
    expect(offtopic.analysis.causes).toEqual([])
    expect(offtopic.departments.every(item => !item.selected)).toBe(true)
    await expect(admin.getByRole('button', { name: '승인', exact: true })).toBeDisabled()
    const customerOfftopic = await (await user.request.get(`${base}/${offtopic.id}`)).json()
    expect(customerOfftopic.status).toBe('정보 요청')
    for (const field of ['analysis', 'departments', 'linked']) expect(customerOfftopic).not.toHaveProperty(field)

    // 3) An identifier lookup: the part and its source list are shown, nothing is guessed.
    const part = await analyse(admin, (await open(`${marker} 부품 번호 2064-75-114-00 이 어떤 부품인지, 어느 기종 부품 목록에 있는지 알려 주세요.`)).id)
    expect(part.analysis.status, 'the known part must actually be found, not merely avoid guessing').toBe('answered')
    await admin.getByRole('tab', { name: '권장 부품', exact: true }).click()
    await expect(admin.getByText('2064-75-114-00', { exact: false }).first()).toBeVisible()
    expect(part.analysis.parts.some(item => /2064-75-114-00/.test(item.name) && /COVER|커버/i.test(item.name))).toBe(true)
    expect(part.analysis.evidence.some(item => /PARTS LIST/i.test(item.title) && /PL-147/.test(item.source))).toBe(true)
    report.part = { status: part.analysis.status, parts: part.analysis.parts.map(item => item.name) }
    console.log(JSON.stringify({ quality_on_screens: true, ...report, offtopic: offtopic.analysis.status }))
  } finally {
    await userContext.close()
    await adminContext.close()
  }
})
