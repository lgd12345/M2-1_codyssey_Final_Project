import { test, expect } from '@playwright/test'

// Real login, API, authorization and PostgreSQL. Only the model call is a controlled server-side double.

async function login(page, loginId, home) {
  await page.goto('/#/login')
  await page.getByLabel('아이디 또는 이메일', { exact: true }).fill(loginId)
  await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_PASSWORD)
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`#/${home}$`))
}

async function newContext(browser, who, home) {
  const context = await browser.newContext()
  const page = await context.newPage()
  page.on('pageerror', error => { throw error })
  await login(page, who, home)
  return { context, page }
}

async function createRequest(page, message) {
  await page.goto('/#/portal/new')
  await page.getByRole('combobox', { name: '접수 사유 *', exact: true }).selectOption('공구 교환 이상')
  await page.getByRole('button', { name: '기종 목록', exact: true }).click()
  await page.getByRole('listbox', { name: '기종 목록', exact: true }).getByRole('option', { name: 'F400', exact: true }).click()
  await page.getByLabel('메시지 *', { exact: true }).fill(message)
  await page.getByRole('button', { name: '계속', exact: true }).click()
  await page.getByLabel('이름 *', { exact: true }).fill('접수 담당자')
  await page.getByLabel('전화번호 *', { exact: true }).fill('010-0000-0000')
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/service-requests') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '전송', exact: true }).click()
  const created = await (await response).json()
  await expect(page).toHaveURL(new RegExp(`#/portal/${created.id}$`))
  return created.id
}

async function analyse(staff, id) {
  await staff.goto(`/#/cases/${id}`)
  await staff.getByRole('button', { name: 'AI 분석 시작', exact: true }).click()
  await expect(staff.getByText('분석 중입니다.', { exact: false })).toBeVisible()
}

const noFollowUp = page => Promise.all(['정보 추가', '콜백 요청', '종결 요청'].map(name =>
  expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)))

const statusButton = (page, name) => page.getByRole('button', { name: new RegExp(`^${name}`) })
const serverItem = async (page, id) => (await page.request.get(`/api/v1/service-requests/${id}`)).json()

test('review edits, approval, department work and closure run through the real UI and are durable', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, 'ATC 교환 중 정지합니다. 승인 흐름 확인.')
  const work = { service: `SVC-${id.slice(4)}`, quality: `QLT-${id.slice(4)}` }

  await analyse(staff.page, id)
  await expect(staff.page.getByText('E2E 통제된 분석 응답', { exact: false })).toBeVisible({ timeout: 15000 })
  await expect(statusButton(staff.page, '검토 대기')).toBeVisible()
  // Review: edit the AI draft, add a department, and approve only after the edit was saved.
  const draft = staff.page.getByLabel('서비스 초안', { exact: true })
  await draft.fill('검토자가 고친 서비스 지시')
  await staff.page.getByRole('checkbox', { name: /품질/ }).click()
  await expect(staff.page.getByRole('checkbox', { name: /품질/ })).toBeChecked()
  // A newly added department has no AI draft, so approval stays blocked until a draft is written.
  await expect(staff.page.getByRole('button', { name: '승인', exact: true })).toBeDisabled()
  await staff.page.getByLabel('품질 초안', { exact: true }).fill('품질 기록 확인 지시')
  await expect(staff.page.getByText('수정됨', { exact: false }).first()).toBeVisible()
  await staff.page.getByRole('button', { name: '승인', exact: true }).click()
  await expect(statusButton(staff.page, '처리 중')).toBeVisible()
  await expect(staff.page.getByText(work.service, { exact: true })).toBeVisible()
  await expect(staff.page.getByText(work.quality, { exact: true })).toBeVisible()
  await expect(staff.page.getByText('검토자가 고친 서비스 지시', { exact: false })).toBeVisible()
  await expect(staff.page.getByText('0/2 완료', { exact: false }).first()).toBeVisible()
  await staff.page.reload()
  await expect(staff.page.getByText('검토자가 고친 서비스 지시', { exact: false })).toBeVisible()
  const approved = await serverItem(staff.page, id)
  expect(approved.linked.map(w => w.workKey)).toEqual([work.service, work.quality])
  expect(approved.linked[0].content).toBe('검토자가 고친 서비스 지시')
  expect(approved.linked[1].content).toBe('품질 기록 확인 지시')

  // Customer: only the customer-safe progress is visible.
  await customer.page.reload()
  await expect(customer.page.getByText('처리 중', { exact: true }).first()).toBeVisible()
  await expect(customer.page.getByText('담당 부서에서 처리를 시작했습니다.', { exact: false })).toBeVisible()
  await expect(customer.page.getByText('검토자가 고친 서비스 지시', { exact: false })).toHaveCount(0)
  await expect(customer.page.getByText(work.service, { exact: false })).toHaveCount(0)

  // Closure is blocked until every linked work item is done.
  await expect(staff.page.getByText('부서 업무가 모두 완료되면 종결할 수 있습니다.', { exact: false })).toBeVisible()
  await staff.page.goto(`/#/work/${work.service}`)
  await staff.page.getByRole('button', { name: '처리 시작', exact: true }).click()
  await expect(staff.page.getByText('진행 중', { exact: true }).first()).toBeVisible()
  await staff.page.getByLabel('조치 내용 *', { exact: true }).fill('ATC 암 구동부 점검 후 정상 확인')
  await staff.page.getByLabel('작업 시간(시간)', { exact: true }).fill('2')
  await staff.page.getByRole('button', { name: '처리 완료', exact: true }).click()
  await expect(staff.page.getByText('ATC 암 구동부 점검 후 정상 확인', { exact: false })).toBeVisible()
  await staff.page.goto(`/#/cases/${id}`)
  await expect(staff.page.getByText('1/2 완료', { exact: false }).first()).toBeVisible()
  await expect(staff.page.getByRole('button', { name: '요청 종결', exact: true })).toHaveCount(0)
  await staff.page.goto(`/#/work/${work.quality}`)
  await staff.page.getByRole('button', { name: '처리 시작', exact: true }).click()
  await staff.page.getByLabel('조치 내용 *', { exact: true }).fill('품질 기록 확인 완료')
  await staff.page.getByRole('button', { name: '처리 완료', exact: true }).click()
  await expect(staff.page.getByText('품질 기록 확인 완료', { exact: false })).toBeVisible()
  await staff.page.goto(`/#/cases/${id}`)
  await staff.page.getByLabel('종결 메모(고객에게 보입니다)', { exact: true }).fill('점검 결과를 안내드렸습니다.')
  await staff.page.getByRole('button', { name: '요청 종결', exact: true }).click()
  await expect(statusButton(staff.page, '종결')).toBeVisible()
  await expect(staff.page.getByText('종결됨', { exact: true })).toBeVisible()
  await staff.page.reload()
  await expect(staff.page.getByText('종결됨', { exact: true })).toBeVisible()
  expect((await serverItem(staff.page, id)).status).toBe('종결')

  await customer.page.reload()
  await expect(customer.page.getByText('이 서비스 요청은 완료되었습니다.', { exact: false })).toBeVisible()
  await expect(customer.page.getByText('점검 결과를 안내드렸습니다.', { exact: false })).toBeVisible()
  await noFollowUp(customer.page)  // a finished request offers nothing to do
  await customer.context.close()
  await staff.context.close()
})

test('decline keeps its reason internal and re-analysis restores a reviewable request', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_COLLEAGUE, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '반려와 재분석 확인용 요청입니다.')
  await analyse(staff.page, id)
  await expect(statusButton(staff.page, '검토 대기')).toBeVisible({ timeout: 15000 })
  await staff.page.getByRole('button', { name: '반려', exact: true }).click()
  await staff.page.getByLabel('반려 사유 (내부 메모로 남습니다)', { exact: false }).fill('내부전용 반려 사유입니다')
  await staff.page.getByRole('button', { name: '반려 확인', exact: true }).click()
  await expect(statusButton(staff.page, '반려됨')).toBeVisible()
  await expect(staff.page.getByText('반려 사유: 내부전용 반려 사유입니다', { exact: false }).first()).toBeVisible()
  await expect(staff.page.getByRole('button', { name: '승인', exact: true })).toHaveCount(0)

  await customer.page.reload()
  await expect(customer.page.getByText('확인 중', { exact: true }).first()).toBeVisible()
  await expect(customer.page.getByText('내부전용 반려 사유', { exact: false })).toHaveCount(0)
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('내부전용')

  await statusButton(staff.page, '반려됨').click()
  await staff.page.getByRole('menuitem', { name: '재분석 요청', exact: true }).click()
  await expect(staff.page.getByText('분석 중입니다.', { exact: false }).or(statusButton(staff.page, '분석 중'))).toBeVisible()
  await expect(statusButton(staff.page, '검토 대기')).toBeVisible({ timeout: 15000 })
  await expect(staff.page.getByText('재분석 1회', { exact: false })).toBeVisible()
  await expect(staff.page.getByRole('button', { name: '승인', exact: true })).toBeEnabled()
  await customer.context.close()
  await staff.context.close()
})

test('insufficient evidence is handled by the operator, who asks publicly and re-analyses', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '근거부족 증상 설명입니다.')
  await analyse(staff.page, id)
  await expect(statusButton(staff.page, '추가 정보 필요')).toBeVisible({ timeout: 15000 })
  await expect(staff.page.getByText('E2E 근거 부족 응답', { exact: false })).toBeVisible()
  await staff.page.getByRole('button', { name: '고객에게 답변', exact: true }).click()
  await staff.page.getByLabel('고객 답변', { exact: true }).fill('알람 번호를 알려 주세요.')
  await staff.page.getByRole('button', { name: '저장', exact: true }).click()
  await expect(staff.page.getByText('알람 번호를 알려 주세요.', { exact: false }).first()).toBeVisible()

  // The customer sees the request for information and how it will continue, but nothing to press.
  await customer.page.reload()
  await expect(customer.page.getByText('서비스 담당자가 추가 정보를 요청했습니다.', { exact: false })).toBeVisible()
  await expect(customer.page.getByText('알람 번호를 알려 주세요.', { exact: false }).first()).toBeVisible()
  await expect(customer.page.getByText('담당자가 저장된 연락처로 연락드립니다.')).toBeVisible()
  await expect(customer.page.getByText('정보 요청', { exact: true }).first()).toBeVisible()
  await noFollowUp(customer.page)

  // The operator re-analyses on their own decision (the customer's request is not an automatic trigger).
  await statusButton(staff.page, '추가 정보 필요').click()
  await staff.page.getByRole('menuitem', { name: '재분석 요청', exact: true }).click()
  await expect(statusButton(staff.page, '검토 대기')).toBeVisible({ timeout: 15000 })
  await expect(staff.page.getByText('재분석 1회', { exact: false })).toBeVisible()
  await customer.page.reload()
  await expect(customer.page.getByText('확인 중', { exact: true }).first()).toBeVisible()
  await customer.context.close()
  await staff.context.close()
})

test('internal notes never reach customers; companies are isolated; customers cannot act on a request', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const other = await newContext(browser, process.env.E2E_OTHER_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '내부 메모 비공개 확인용입니다.')
  await noFollowUp(customer.page)

  await staff.page.goto(`/#/cases/${id}`)
  await staff.page.getByRole('button', { name: '나에게 지정', exact: true }).click()
  await expect(staff.page.getByText('담당자로 지정', { exact: false })).toBeVisible()
  await staff.page.getByRole('button', { name: '내부 메모 추가', exact: true }).click()
  await staff.page.getByLabel('내부 메모', { exact: true }).fill('내부 전용 메모입니다')
  await staff.page.getByRole('button', { name: '저장', exact: true }).click()
  await expect(staff.page.getByText('내부 전용 메모입니다', { exact: false })).toBeVisible()
  await staff.page.getByRole('button', { name: '고객에게 답변', exact: true }).click()
  await staff.page.getByLabel('고객 답변', { exact: true }).fill('곧 연락드리겠습니다.')
  await staff.page.getByRole('button', { name: '저장', exact: true }).click()

  await customer.page.reload()
  await expect(customer.page.getByText('곧 연락드리겠습니다.', { exact: false })).toBeVisible()
  await expect(customer.page.getByText('내부 전용 메모', { exact: false })).toHaveCount(0)
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('내부 전용')
  // A different company can neither read it nor reach any action on it.
  const otherHeaders = { Origin: new URL(other.page.url()).origin, 'X-CSRF-Token': (await (await other.page.request.get('/api/v1/auth/me')).json()).csrf_token }
  expect((await other.page.request.get(`/api/v1/service-requests/${id}`)).status()).toBe(404)
  // A customer cannot call operator actions, and the old customer follow-up endpoints no longer exist.
  const customerHeaders = { Origin: new URL(customer.page.url()).origin, 'X-CSRF-Token': (await (await customer.page.request.get('/api/v1/auth/me')).json()).csrf_token }
  expect((await customer.page.request.post(`/api/v1/service-requests/${id}/approval`, { headers: customerHeaders })).status()).toBe(403)
  for (const suffix of ['replies', 'callback', 'close-request']) {
    expect([404, 405]).toContain((await customer.page.request.post(`/api/v1/service-requests/${id}/${suffix}`, { headers: customerHeaders, data: { text: 'x', reason: 'y' } })).status())
    expect([404, 405]).toContain((await other.page.request.post(`/api/v1/service-requests/${id}/${suffix}`, { headers: otherHeaders, data: { text: 'x', reason: 'y' } })).status())
  }
  await customer.context.close(); await other.context.close(); await staff.context.close()
})
