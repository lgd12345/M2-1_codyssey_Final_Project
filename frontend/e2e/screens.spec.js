import { test, expect } from '@playwright/test'

// Every screen and control of the product through the real browser, API, authorization and PostgreSQL.
// Only the model call is a controlled server-side double (backend/tests/e2e_app.py); no real LLM is used.
// Attachments are not part of the product: the intake form must not offer them.

const API = '/api/v1/service-requests'
const PAGE_BUDGET = 15000

async function signIn(page, loginId, home) {
  await page.goto('/#/login')
  await page.getByLabel('아이디 또는 이메일', { exact: true }).fill(loginId)
  await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_PASSWORD)
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`#/${home}$`))
}

async function session(browser, loginId, home, options = {}) {
  const context = await browser.newContext(options)
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await signIn(page, loginId, home)
  return { context, page, errors }
}

const closeAll = async (...sessions) => { for (const s of sessions) await s.context.close() }

async function chooseMachine(page) {
  await page.getByRole('button', { name: '기종 목록', exact: true }).click()
  await page.getByRole('listbox', { name: '기종 목록', exact: true }).getByRole('option', { name: 'F400', exact: true }).click()
}

// Customer intake through the real form. `portal` false = the operator's own "새 요청" modal.
async function createRequest(page, { reason = '공구 교환 이상', message, portal = true }) {
  await page.goto(portal ? '/#/portal/new' : '/#/cases/new')
  await page.getByRole('combobox', { name: '접수 사유 *', exact: true }).selectOption(reason)
  await chooseMachine(page)
  await page.getByLabel('메시지 *', { exact: true }).fill(message)
  const response = page.waitForResponse(r => r.url().endsWith(API) && r.request().method() === 'POST')
  await page.getByRole('button', { name: '전송', exact: true }).click()
  const created = await (await response).json()
  await expect(page).toHaveURL(new RegExp(`#/${portal ? 'portal' : 'cases'}/${created.id}$`))
  return created.id
}

const serverItem = async (page, id) => (await page.request.get(`${API}/${id}`)).json()
const statusBadge = (page, name) => page.getByRole('status', { name: `상태 ${name}` })
const rowFor = (page, id) => page.getByRole('row').filter({ hasText: id })

// A request is 처리 중 from the moment the analysis starts; the analysis is finished once the conversation opens.
async function analyse(staff, id) {
  await staff.goto(`/#/cases/${id}`)
  await staff.getByRole('button', { name: '분석해줘', exact: true }).click()
  await expect(staff.getByLabel('질문 입력', { exact: true })).toBeEnabled({ timeout: PAGE_BUDGET })
}

const optionWith = async (select, text) => (await select.locator('option', { hasText: text }).first().textContent())
// [] when the page fits the viewport; otherwise the elements sticking out, so a failure names its cause.
const overflowing = page => page.evaluate(() => {
  const root = document.documentElement
  if (root.scrollWidth <= root.clientWidth + 1) return []
  // Content inside its own horizontal scroller (a wide table) is allowed to be wider than the screen.
  const scrolls = el => { for (let up = el.parentElement; up && up !== document.body; up = up.parentElement) { if (['auto', 'scroll', 'hidden'].includes(getComputedStyle(up).overflowX)) return true } return false }
  const culprits = [...document.querySelectorAll('body *')]
    .filter(el => el.getBoundingClientRect().right > root.clientWidth + 1 && getComputedStyle(el).position !== 'fixed' && !scrolls(el))
    .slice(0, 6).map(el => `${el.tagName.toLowerCase()}.${String(el.className).split(' ').join('.')} right=${Math.round(el.getBoundingClientRect().right)}/${root.clientWidth}`)
  // The page itself is wider than the screen even if no single element is to blame: never report that as fine.
  return culprits.length ? culprits : [`document is ${root.scrollWidth}px wide in a ${root.clientWidth}px viewport`]
})

// ---------------------------------------------------------------------------------------------------------------
// Public area
// ---------------------------------------------------------------------------------------------------------------

test('public home, support and login pages work without an account', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))

  await page.goto('/#/')
  await expect(page).toHaveURL(/#\/home$/)
  await expect(page).toHaveTitle(/공작기계 고객지원 \| MORRONO/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('정밀한 기술')
  const hero = page.locator('.hero-image')
  await expect(hero).toBeVisible()
  expect(await hero.evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true)
  const nav = page.getByRole('navigation', { name: '주 메뉴' })
  await expect(nav.getByRole('link', { name: '공작기계 소개', exact: true })).toBeVisible()
  await expect(nav.getByRole('link', { name: '고객센터', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: /^로그인/ }).first()).toBeVisible()

  // "공작기계 알아보기" scrolls to the introduction instead of leaving the page.
  await page.getByRole('link', { name: /공작기계 알아보기/ }).click()
  await expect(page.locator('#machines')).toBeInViewport()
  await expect(page.getByRole('heading', { name: /가능성을 만드는/ })).toBeVisible()
  await expect(page.locator('dt', { hasText: '머시닝센터' })).toBeVisible()
  await expect(page.locator('dt', { hasText: 'CNC 선반' })).toBeVisible()

  // Footer: how AI is used (customers never read raw AI output) and image credits.
  await expect(page.getByText('A/S 요청 분석에 AI를 활용하며, 고객께 드리는 답변은 서비스 담당자가 검토해 작성합니다.')).toBeVisible()
  await expect(page.getByText('AI가 생성한 답변은', { exact: false })).toHaveCount(0)
  await page.getByText('사진 출처', { exact: true }).click()
  await expect(page.getByRole('link', { name: 'Unsplash License' })).toBeVisible()

  // Home -> support -> login -> back.
  await page.getByRole('link', { name: /고객센터 문의/ }).click()
  await expect(page).toHaveURL(/#\/support$/)
  await expect(page).toHaveTitle(/고객센터 \| MORRONO/)
  await expect(page.getByRole('heading', { name: '무엇을 도와드릴까요?' })).toBeVisible()
  await expect(page.getByText('온라인 회원가입과 비회원 문의는 준비 중입니다.', { exact: false })).toBeVisible()
  await expect(page.getByRole('link', { name: /회원가입/ })).toHaveCount(0)  // not offered, so no dead link
  await page.getByRole('link', { name: /로그인하기/ }).click()
  await expect(page).toHaveURL(/#\/login$/)
  // Customers never receive raw AI answers, so the login page explains the AI's role instead of claiming it writes the answers.
  const aiUse = page.getByRole('note', { name: 'AI 활용 안내' })
  await expect(aiUse).toContainText('AI가 먼저 분석하고, 서비스 담당자가 검토한 뒤 답변합니다.')
  await expect(page.getByText('로그인 후 제공되는 답변은 AI가 생성합니다', { exact: false })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeDisabled()
  await page.getByRole('link', { name: '← 고객센터' }).click()
  await expect(page).toHaveURL(/#\/support$/)
  await page.getByRole('link', { name: /^MORRONO/ }).first().click()
  await expect(page).toHaveURL(/#\/home$/)

  // Unknown addresses end on an explanation with a way out.
  await page.goto('/#/no-such-page')
  await expect(page.getByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeVisible()
  await page.getByRole('link', { name: '처음으로' }).click()
  await expect(page).toHaveURL(/#\/home$/)
  expect(errors).toEqual([])
})

test('theme preference cycles, is applied to the page and survives a reload; the skip link is first', async ({ page }) => {
  await page.goto('/#/home')
  const toggle = page.getByRole('button', { name: /^화면 테마:/ })
  await expect(toggle).toHaveAttribute('aria-label', '화면 테마: 시스템 설정. 다음 테마: 라이트')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-label', '화면 테마: 라이트. 다음 테마: 다크')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await toggle.click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.getByRole('button', { name: /^화면 테마: 다크/ })).toBeVisible()
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-label', '화면 테마: 시스템 설정. 다음 테마: 라이트')

  await page.goto('/#/support')
  await page.reload()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: '본문으로 이동' })).toBeFocused()
})

// ---------------------------------------------------------------------------------------------------------------
// Sign in, role routing, guards, sign out
// ---------------------------------------------------------------------------------------------------------------

test('private pages need a session, wrong credentials are refused, roles are routed and sign out ends the session', async ({ browser, page }) => {
  for (const hash of ['cases', 'cases/new', 'cases/CLM-001', 'portal', 'portal/new', 'portal/CLM-001', 'departments']) {
    await page.goto(`/#/${hash}`)
    await expect(page).toHaveURL(/#\/login$/)
  }
  expect((await (await page.request.get('/api/v1/auth/me')).json()).authenticated).toBe(false)
  expect((await page.request.get(API)).status()).toBe(401)

  // Wrong password: stays on the form, tells the user, clears the password, creates no session.
  await page.getByLabel('아이디 또는 이메일', { exact: true }).fill(process.env.E2E_CUSTOMER)
  await page.getByLabel('비밀번호', { exact: true }).fill('definitely-not-the-password')
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/#\/login$/)
  await expect(page.getByLabel('비밀번호', { exact: true })).toHaveValue('')
  expect((await (await page.request.get('/api/v1/auth/me')).json()).authenticated).toBe(false)
  await page.getByLabel('아이디 또는 이메일', { exact: true }).fill('nobody-with-this-id')
  await page.getByLabel('비밀번호', { exact: true }).fill('definitely-not-the-password')
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()

  // Customer: portal home, customer menu only, operator and department pages are closed to them.
  const customer = await session(browser, process.env.E2E_CUSTOMER, 'portal')
  const menu = customer.page.getByRole('navigation', { name: '고객 메뉴' })
  await expect(menu.getByRole('link', { name: '내 서비스 요청' })).toHaveAttribute('aria-current', 'page')
  await expect(customer.page.getByRole('navigation', { name: '업무 메뉴' })).toHaveCount(0)
  await expect(customer.page.locator('.header-account')).toHaveText(process.env.E2E_CUSTOMER)
  for (const hash of ['cases', 'cases/new', 'departments', 'login']) {
    await customer.page.goto(`/#/${hash}`)
    await expect(customer.page).toHaveURL(/#\/portal$/)
  }
  await customer.page.reload()
  await expect(customer.page).toHaveURL(/#\/portal$/)  // the session survives a reload
  expect((await customer.page.request.get(`${API}/context`)).status()).toBe(200)

  // Operator: queue home, operator menu, both work areas open.
  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const ops = staff.page.getByRole('navigation', { name: '업무 메뉴' })
  await expect(ops.getByRole('link', { name: '대기열' })).toHaveAttribute('aria-current', 'page')
  await expect(ops.getByRole('link', { name: '받은 업무' })).toHaveCount(0)  // department work is gone
  await ops.getByRole('link', { name: '부서 메일' }).click()
  await expect(staff.page).toHaveURL(/#\/departments$/)
  await expect(ops.getByRole('link', { name: '부서 메일' })).toHaveAttribute('aria-current', 'page')
  await expect(staff.page.getByRole('navigation', { name: '고객 메뉴' })).toHaveCount(0)
  await expect(staff.page.getByText('AI 분석은 검토용 초안입니다. 인용된 근거와 원본 매뉴얼을 확인해 주세요.')).toBeVisible()  // operator footer
  await staff.page.goto('/#/login')
  await expect(staff.page).toHaveURL(/#\/cases$/)

  // Sign out: back to the public home, the server session is gone, private pages are closed again.
  await staff.page.getByRole('button', { name: '로그아웃', exact: true }).click()
  await expect(staff.page).toHaveURL(/#\/home$/)
  expect((await (await staff.page.request.get('/api/v1/auth/me')).json()).authenticated).toBe(false)
  expect((await staff.page.request.get(API)).status()).toBe(401)
  await staff.page.goto('/#/cases')
  await expect(staff.page).toHaveURL(/#\/login$/)
  await expect(staff.page.getByRole('link', { name: /^로그인/ }).first()).toBeVisible()
  // The other person's session is unaffected.
  expect((await (await customer.page.request.get('/api/v1/auth/me')).json()).authenticated).toBe(true)
  expect(customer.errors).toEqual([])
  expect(staff.errors).toEqual([])
  await closeAll(customer, staff)
})

// ---------------------------------------------------------------------------------------------------------------
// Intake form
// ---------------------------------------------------------------------------------------------------------------

test('intake form: reason, model and message submit directly with the logged-in identity', async ({ browser }) => {
  const customer = await session(browser, process.env.E2E_CUSTOMER, 'portal')
  const { page } = customer
  await page.goto('/#/portal/new')
  const dialog = page.getByRole('dialog', { name: '새 서비스 요청' })
  await expect(dialog).toBeVisible()
  for (const label of ['이름 *', '전화번호 *', '이메일', '오류 번호 1']) {
    await expect(dialog.getByLabel(label, { exact: true })).toHaveCount(0)
  }
  await expect(dialog.locator('input[type="file"]')).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: '계속', exact: true })).toHaveCount(0)
  const send = dialog.getByRole('button', { name: '전송', exact: true })
  await expect(send).toBeDisabled()
  await dialog.getByRole('combobox', { name: '접수 사유 *' }).selectOption('부품 교체·문의')
  await expect(send).toBeDisabled()
  await chooseMachine(page)
  await expect(send).toBeDisabled()
  await dialog.getByLabel('메시지 *', { exact: true }).fill('   ')
  await expect(send).toBeDisabled()
  await dialog.getByLabel('메시지 *', { exact: true }).fill('부품 교체 시기를 알고 싶습니다. 입력 확인용')
  await expect(send).toBeEnabled()
  let sent = 0
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith(API)) sent += 1 })
  const response = page.waitForResponse(r => r.url().endsWith(API) && r.request().method() === 'POST')
  await send.click()
  const created = await (await response).json()
  await expect(page).toHaveURL(new RegExp(`#/portal/${created.id}$`))
  const stored = await serverItem(page, created.id)
  expect(stored.intake.type).toBe('부품 교체·문의')
  expect(stored.intake.creator).toContain(process.env.E2E_CUSTOMER)
  expect(stored.intake).not.toHaveProperty('contact')
  await expect(page.getByRole('tab', { name: '연락처', exact: true })).toHaveCount(0)
  await expect(page.getByText('부품 교체 시기를 알고 싶습니다. 입력 확인용').first()).toBeVisible()
  for (const dismiss of [
    () => page.keyboard.press('Escape'),
    () => page.getByRole('button', { name: '닫기', exact: true }).click(),
    () => page.mouse.click(4, 4),
  ]) {
    await page.goto('/#/portal/new')
    await expect(page.getByRole('dialog', { name: '새 서비스 요청' })).toBeVisible()
    await dismiss()
    await expect(page).toHaveURL(/#\/portal$/)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  await page.goto('/#/portal/new')
  await page.getByRole('button', { name: '취소', exact: true }).click()
  await expect(page).toHaveURL(/#\/portal$/)
  expect(sent).toBe(1)
  expect(customer.errors).toEqual([])
  await closeAll(customer)
})

test('an account without a company cannot file requests and is told why; operators can file on behalf of equipment', async ({ browser }) => {
  const nobody = await session(browser, process.env.E2E_UNASSIGNED, 'portal')
  await expect(nobody.page.getByText('고객사 소속이 등록되지 않았습니다.', { exact: false })).toBeVisible()
  await expect(nobody.page.getByText('조건에 맞는 서비스 요청이 없습니다.')).toBeVisible()
  await nobody.page.goto('/#/portal/new')
  const dialog = nobody.page.getByRole('dialog', { name: '새 서비스 요청' })
  await expect(dialog.getByRole('status')).toContainText('선택할 수 있는 기종이 없습니다')
  await expect(dialog.getByRole('combobox', { name: '기종 *' })).toBeDisabled()
  await expect(dialog.getByRole('button', { name: '전송', exact: true })).toBeDisabled()
  const forced = await nobody.page.request.post(API, {
    headers: { Origin: new URL(nobody.page.url()).origin, 'X-CSRF-Token': (await (await nobody.page.request.get('/api/v1/auth/me')).json()).csrf_token },
    data: { equipment_id: '00000000-0000-0000-0000-000000000000', reason: '공구 교환 이상', message: 'x', alarm_numbers: [] } })
  expect(forced.status()).toBeGreaterThanOrEqual(400)
  await closeAll(nobody)

  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(staff.page, { message: '운영진이 대신 접수한 요청입니다.', portal: false })
  await expect(staff.page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(staff.page.getByRole('button', { name: '분석해줘', exact: true })).toBeVisible()
  await expect(staff.page.getByText('운영진이 대신 접수한 요청입니다.').first()).toBeVisible()
  expect((await serverItem(staff.page, id)).status).toBe('접수됨')
  await staff.page.goto('/#/cases/new')
  await expect(staff.page.getByRole('dialog', { name: '새 서비스 요청' })).toBeVisible()
  await staff.page.keyboard.press('Escape')
  await expect(staff.page).toHaveURL(/#\/cases$/)
  expect(staff.errors).toEqual([])
  await closeAll(staff)
})

// ---------------------------------------------------------------------------------------------------------------
// Customer portal: list, filters, sorting, company sharing, detail
// ---------------------------------------------------------------------------------------------------------------

test('customer list: company sharing, every filter, sorting and the customer-safe detail', async ({ browser }) => {
  const alice = await session(browser, process.env.E2E_CUSTOMER, 'portal')
  const colleague = await session(browser, process.env.E2E_COLLEAGUE, 'portal')
  const bob = await session(browser, process.env.E2E_OTHER_CUSTOMER, 'portal')
  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const first = await createRequest(alice.page, { reason: '공구 교환 이상', message: '목록 확인 첫째 요청' })
  const second = await createRequest(colleague.page, { reason: '알람·전장 이상', message: '목록 확인 둘째 요청' })
  const foreign = await createRequest(bob.page, { reason: '공구 교환 이상', message: '다른 회사의 요청' })
  await analyse(staff.page, first)

  // The whole company sees the same requests; another company sees none of them.
  await alice.page.goto('/#/portal')
  for (const id of [first, second]) await expect(rowFor(alice.page, id)).toBeVisible()
  await expect(rowFor(alice.page, foreign)).toHaveCount(0)
  await bob.page.goto('/#/portal')
  await expect(rowFor(bob.page, foreign)).toBeVisible()
  await expect(rowFor(bob.page, first)).toHaveCount(0)
  await expect(alice.page.getByText('의 서비스 요청을 한곳에서 확인합니다.', { exact: false })).toBeVisible()

  // Internal status names never reach the customer: an analysed request is simply "처리 중".
  await expect(rowFor(alice.page, first).getByText('처리 중', { exact: true })).toBeVisible()
  await expect(rowFor(alice.page, second).getByText('접수됨', { exact: true })).toBeVisible()
  await expect(alice.page.getByText('검토 대기', { exact: true })).toHaveCount(0)

  const page = alice.page
  const total = page.getByText(/^총 \d+건$/)
  // Status filter + removable chip.
  await page.getByRole('combobox', { name: '상태', exact: true }).selectOption('처리 중')
  await expect(rowFor(page, first)).toBeVisible()
  await expect(rowFor(page, second)).toHaveCount(0)
  await page.getByRole('button', { name: '상태: 처리 중 ×' }).click()
  await expect(rowFor(page, second)).toBeVisible()
  // Type filter.
  await page.getByRole('combobox', { name: '유형', exact: true }).selectOption('알람·전장 이상')
  await expect(rowFor(page, second)).toBeVisible()
  await expect(rowFor(page, first)).toHaveCount(0)
  await page.getByRole('button', { name: '유형: 알람·전장 이상 ×' }).click()
  // Creator filter (options are the people who filed).
  await page.getByRole('combobox', { name: '접수자', exact: true }).selectOption({ label: await optionWith(page.getByRole('combobox', { name: '접수자', exact: true }), process.env.E2E_COLLEAGUE) })
  await expect(rowFor(page, second)).toBeVisible()
  await expect(rowFor(page, first)).toHaveCount(0)
  await page.getByRole('button', { name: /^접수자: .* ×$/ }).click()
  // Machine filter keeps both (same machine type) and offers only machines of this company.
  await page.getByRole('combobox', { name: '기계', exact: true }).selectOption('F400')
  await expect(rowFor(page, first)).toBeVisible()
  await page.getByRole('button', { name: '기계: F400 ×' }).click()
  // Date range: today keeps them, a future start hides them, the empty state explains itself.
  const filedOn = (await rowFor(page, first).getByRole('cell').nth(5).textContent()).trim()
  await page.getByLabel('시작일', { exact: true }).fill(filedOn)
  await page.getByLabel('종료일', { exact: true }).fill(filedOn)
  await expect(rowFor(page, first)).toBeVisible()
  await page.getByLabel('시작일', { exact: true }).fill('2099-01-01')
  await expect(page.getByText('조건에 맞는 서비스 요청이 없습니다.')).toBeVisible()
  await expect(total).toHaveText('총 0건')
  await page.getByRole('button', { name: /^시작일: / }).click()
  await page.getByRole('button', { name: /^종료일: / }).click()
  await expect(rowFor(page, first)).toBeVisible()

  // Sorting by a column header toggles direction and announces it.
  const ids = async () => (await page.locator('tbody a.key').allTextContents())
  const header = page.getByRole('columnheader', { name: /요청 번호/ })
  await header.getByRole('button').click()
  await expect(header).toHaveAttribute('aria-sort', 'ascending')
  expect(await ids()).toEqual([...(await ids())].sort())
  await header.getByRole('button').click()
  await expect(header).toHaveAttribute('aria-sort', 'descending')
  expect(await ids()).toEqual([...(await ids())].sort().reverse())

  // Detail: facts, history, guides (none before the request is closed), and no contact or follow-up controls.
  await page.getByRole('link', { name: `${first} 상세 보기` }).click()
  await expect(page).toHaveURL(new RegExp(`#/portal/${first}$`))
  const facts = page.locator('.pd-meta')
  await expect(facts).toContainText(first)
  await expect(facts).toContainText(process.env.E2E_CUSTOMER)
  await expect(facts.getByText('처리 중', { exact: true })).toBeVisible()
  await expect(page.getByText('목록 확인 첫째 요청').first()).toBeVisible()
  await expect(page.getByRole('tab', { name: '이력', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('heading', { name: '요청 이력' })).toBeVisible()
  await page.getByRole('tab', { name: '기술 가이드', exact: true }).click()
  await expect(page.getByText('해당하는 기술 가이드가 아직 없습니다.', { exact: false })).toBeVisible()
  await expect(page.getByRole('tab', { name: '연락처', exact: true })).toHaveCount(0)
  for (const hidden of ['AI 분석', 'E2E 통제된 분석 응답', '연결 업무', '내부 메모', '승인']) {
    await expect(page.getByText(hidden, { exact: false })).toHaveCount(0)
  }
  // After filing there is nothing for a customer to press: no information, callback or close-request actions.
  for (const name of ['정보 추가', '콜백 요청', '종결 요청']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  await expect(page.locator('.pd-actions')).toHaveCount(0)
  await page.getByRole('tab', { name: '이력', exact: true }).click()
  await expect(page.getByText('서비스 요청이 접수되었습니다.')).toBeVisible()
  // Another company cannot open it.
  await bob.page.goto(`/#/portal/${first}`)
  await expect(bob.page.getByRole('heading', { name: /찾을 수 없습니다|불러오지 못했습니다/ })).toBeVisible()
  expect(alice.errors.concat(colleague.errors, bob.errors, staff.errors)).toEqual([])
  await closeAll(alice, colleague, bob, staff)
})

// ---------------------------------------------------------------------------------------------------------------
// Operator queue
// ---------------------------------------------------------------------------------------------------------------

test('operator queue: counts per status, search, every filter, empty state and navigation', async ({ browser }) => {
  const alice = await session(browser, process.env.E2E_CUSTOMER, 'portal')
  const colleague = await session(browser, process.env.E2E_COLLEAGUE, 'portal')
  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const analysed = await createRequest(alice.page, { reason: '공구 교환 이상', message: '대기열 확인 분석 대상' })
  const waiting = await createRequest(colleague.page, { reason: '교육·기술지원', message: '대기열 확인 접수 대상' })
  const page = staff.page
  await page.reload()  // the list loaded at sign-in predates the two requests filed above
  const side = page.getByRole('complementary', { name: '대기열' })
  const count = async name => Number((await side.getByRole('button', { name: new RegExp(`^${name}`) }).locator('.count').textContent()).trim())
  const before = await count('처리 중')
  const beforeNew = await count('접수됨')
  await analyse(page, analysed)
  await page.goto('/#/cases')
  await page.reload()
  expect(await count('처리 중')).toBe(before + 1)
  expect(await count('접수됨')).toBe(beforeNew - 1)  // the analysed request left "접수됨"
  const all = await count('모든 요청')
  await expect(page.getByText(`총 ${all}건`)).toBeVisible()
  expect(all).toBeGreaterThanOrEqual(2)

  // Queue buttons filter by status and mark the current one.
  await side.getByRole('button', { name: /^처리 중/ }).click()
  await expect(side.getByRole('button', { name: /^처리 중/ })).toHaveAttribute('aria-current', 'true')
  await expect(rowFor(page, analysed)).toBeVisible()
  await expect(rowFor(page, waiting)).toHaveCount(0)
  await side.getByRole('button', { name: /^접수됨/ }).click()
  await expect(rowFor(page, waiting)).toBeVisible()
  await expect(rowFor(page, analysed)).toHaveCount(0)
  await side.getByRole('button', { name: /^모든 요청/ }).click()

  // Search by id, by title text and by nothing.
  const search = page.getByRole('searchbox', { name: '검색' })
  await search.fill(waiting)
  await expect(rowFor(page, waiting)).toBeVisible()
  await expect(rowFor(page, analysed)).toHaveCount(0)
  await expect(page.getByText('총 1건')).toBeVisible()
  await search.fill('절대로-없는-검색어')
  await expect(page.getByText('조건에 맞는 요청이 없습니다.')).toBeVisible()
  await expect(page.getByText('총 0건')).toBeVisible()
  await search.fill('')

  // Filters combine; chips remove one filter; "모두 지우기" removes all.
  await page.getByRole('combobox', { name: '유형', exact: true }).selectOption('교육·기술지원')
  await expect(rowFor(page, waiting)).toBeVisible()
  await expect(rowFor(page, analysed)).toHaveCount(0)
  await page.getByRole('combobox', { name: '접수자', exact: true }).selectOption({ label: await optionWith(page.getByRole('combobox', { name: '접수자', exact: true }), process.env.E2E_COLLEAGUE) })
  await expect(rowFor(page, waiting)).toBeVisible()
  await page.getByRole('combobox', { name: '기계', exact: true }).selectOption('F400')
  const chips = page.getByLabel('적용된 필터')
  await expect(chips.getByRole('button')).toHaveCount(4)  // 3 filters + "모두 지우기"
  await chips.getByRole('button', { name: '유형: 교육·기술지원 ×' }).click()
  await expect(chips.getByRole('button')).toHaveCount(3)
  await chips.getByRole('button', { name: '모두 지우기' }).click()
  await expect(chips).toHaveCount(0)
  await expect(rowFor(page, analysed)).toBeVisible()
  await page.getByLabel('시작일', { exact: true }).fill('2099-01-01')
  await expect(page.getByText('총 0건')).toBeVisible()
  await chips.getByRole('button', { name: '모두 지우기' }).click()
  await page.getByLabel('종료일', { exact: true }).fill('2000-01-01')
  await expect(page.getByText('총 0건')).toBeVisible()
  await chips.getByRole('button', { name: '모두 지우기' }).click()

  // Navigation: the "새 요청" button opens the form; a row opens the detail; "뒤로" returns.
  await page.getByRole('link', { name: '새 요청', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '새 서비스 요청' })).toBeVisible()
  // Escape is idempotent: repeat until the key handler (attached just after the dialog paints) has taken it.
  await expect.poll(async () => { await page.keyboard.press('Escape'); return new URL(page.url()).hash }).toBe('#/cases')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('link', { name: `${analysed} 상세 보기` }).click()
  await expect(page).toHaveURL(new RegExp(`#/cases/${analysed}$`))
  await page.getByRole('link', { name: '← 뒤로' }).click()
  await expect(page).toHaveURL(/#\/cases$/)
  await page.goto('/#/cases/CLM-999999')
  await expect(page.getByRole('heading', { name: /찾을 수 없습니다|불러오지 못했습니다/ })).toBeVisible()
  expect(alice.errors.concat(colleague.errors, staff.errors)).toEqual([])
  await closeAll(alice, colleague, staff)
})

// ---------------------------------------------------------------------------------------------------------------
// Operator detail: AI panels, evidence, department proposals, notes, approval, department inbox
// ---------------------------------------------------------------------------------------------------------------

test('operator detail: AI tabs and evidence, original pages, notes, department proposals and reset', async ({ browser }) => {
  const customer = await session(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, { message: 'ATC 교환 중 정지합니다. 화면 점검용.' })
  const page = staff.page
  await page.goto(`/#/cases/${id}`)

  // Before analysis: nothing is pretended.
  await expect(page.getByText('아직 분석 결과가 없습니다.')).toBeVisible()
  await expect(page.getByText('미분석', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '처리 대기' })).toBeVisible()
  await expect(page.getByText('연결 업무', { exact: true })).toHaveCount(0)  // the rest appears after the analysis
  await expect(page.getByRole('button', { name: '승인', exact: true })).toHaveCount(0)

  // Request card can be collapsed.
  const toggleDetails = page.getByRole('button', { name: '세부 정보 숨기기' })
  await expect(page.getByText('발생 상황')).toBeVisible()
  await toggleDetails.click()
  await expect(page.getByText('발생 상황')).toHaveCount(0)
  await page.getByRole('button', { name: '세부 정보 보기' }).click()
  await expect(page.getByText('발생 상황')).toBeVisible()

  await analyse(page, id)
  await expect(page.getByText('분석 중입니다.', { exact: false })).toHaveCount(0)
  await expect(page.getByText('E2E 통제된 분석 응답', { exact: false })).toBeVisible()
  await expect(page.getByText('✦ AI 생성')).toBeVisible()
  await expect(page.getByText('AI가 작성한 검토용 초안입니다. 인용된 근거와 원본 매뉴얼을 확인한 뒤 판단해 주세요.', { exact: false })).toBeVisible()

  // Short by design: causes with their sources, then the recommended activities. No tabs, steps or parts here.
  await expect(page.getByRole('tab', { name: '문제 해결 단계', exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '원인 후보' })).toBeVisible()
  await expect(page.getByText('ATC 암 구동 불량', { exact: true })).toBeVisible()
  await expect(page.getByText('가능성 높음', { exact: true })).toBeVisible()
  await expect(page.getByText('출처: E2E 매뉴얼 p.45 · FSR-00001 · VMCT-05')).toBeVisible()
  await expect(page.getByText('알람 이력 확인', { exact: true })).toHaveCount(0)
  await expect(page.getByText('ATC 암 모터', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '권장 활동 1건' })).toBeVisible()
  await expect(page.getByRole('list', { name: '권장 활동' }).getByText('서비스맨 출동 요청 메일', { exact: true })).toBeVisible()
  // Past cases fold open; the excerpt opens and closes and carries its caution.
  await page.getByText('과거 사례 1건 (보기)', { exact: true }).click()
  const fsr = page.getByRole('button', { name: /FSR-00001/ })
  await expect(fsr).toHaveAttribute('aria-expanded', 'false')
  await fsr.click()
  await expect(fsr).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('공구 교환 중 정지', { exact: true })).toBeVisible()
  await expect(page.getByText('적용 시 주의: 과거 사례는 참고용입니다.', { exact: false })).toBeVisible()
  await fsr.click()
  await expect(page.getByText('공구 교환 중 정지', { exact: true })).toHaveCount(0)
  // Manuals fold open too.
  await page.getByText('관련 문서 1건 (보기)', { exact: true }).click()
  await page.getByRole('button', { name: /E2E 매뉴얼/ }).click()
  await expect(page.getByText('ATC 구동부 점검 절차', { exact: true })).toBeVisible()
  await expect(page.getByText('적용 시 주의: 변환 텍스트입니다.', { exact: false })).toBeVisible()
  // The original page of a manual citation opens as an image; a refused or missing page is explained.
  await page.getByRole('button', { name: '원본 페이지 보기', exact: true }).click()
  const original = page.getByRole('dialog', { name: /원본 페이지 · E2E 매뉴얼/ })
  await expect(original.getByRole('img', { name: /원본 페이지/ })).toBeVisible()
  expect(await original.getByRole('img').evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true)
  await expect(original.getByText('원본 PDF를 이미지로 변환한 페이지입니다.')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.route('**/evidence/E1/page', route => route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"x","code":"SOURCE_UNAVAILABLE"}' }))  // network stub
  await page.getByRole('button', { name: '원본 페이지 보기', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('원본 PDF 페이지를 열 수 없습니다')
  await page.keyboard.press('Escape')
  await page.unroute('**/evidence/E1/page')

  // The AI answer cannot be rated: no rating buttons, and nothing rating-related is stored with the analysis.
  for (const name of ['도움이 됨', '도움이 안 됨']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  expect(await serverItem(page, id)).not.toHaveProperty('analysis.feedback')
  await expect(page.getByText('지식 근거', { exact: true })).toBeVisible()
  await expect(page.getByText('2건 (매뉴얼 1, 과거 사례 1)', { exact: true })).toBeVisible()

  // Customers never see the AI summary.
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('E2E 통제된 분석 응답')

  // History: a plain list of what happened. No note or reply inputs and no filters: the conversation and mail do the talking.
  const history = page.getByRole('region', { name: '이력' })
  await expect(history.locator('li.event').first()).toBeVisible()
  await expect(history.getByRole('tab')).toHaveCount(0)
  for (const name of ['내부 메모 추가', '고객에게 답변', '내부 메모로 복사']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)

  // The old review controls are gone: no department selection or drafts, approval, decline, assignee or status menu.
  for (const name of ['승인', '반려', '나에게 지정']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await expect(page.getByText('연결 업무', { exact: true })).toHaveCount(0)
  await expect(page.getByText('대상 부서', { exact: true })).toHaveCount(0)
  await expect(page.getByText('담당자', { exact: true })).toHaveCount(0)
  await expect(statusBadge(page, '처리 중')).toBeVisible()
  expect((await serverItem(page, id)).status).toBe('처리 중')
  expect(customer.errors.concat(staff.errors)).toEqual([])
  await closeAll(customer, staff)
})

test('closing: the result and the guides reach the customer together, and not before', async ({ browser }) => {
  const customer = await session(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, { message: '종결 안내 확인용 요청입니다.' })
  const page = staff.page
  await analyse(page, id)

  // While the request is being processed the customer sees progress only: no guides, no page, no result.
  expect((await customer.page.request.get(`/api/v1/service-requests/${id}/evidence/E1/page`)).status()).toBe(404)
  await customer.page.goto(`/#/portal/${id}`)
  await customer.page.getByRole('tab', { name: '기술 가이드', exact: true }).click()
  await expect(customer.page.getByText('E2E 매뉴얼', { exact: true })).toHaveCount(0)

  // The operator writes the result once; closing is the operator's own button.
  await page.getByLabel('처리 결과 (고객에게 보입니다)', { exact: true }).fill('ATC 구동부를 점검하고 정상 동작을 확인했습니다.')
  await page.getByRole('button', { name: '요청 종결', exact: true }).click()
  await expect(statusBadge(page, '종결')).toBeVisible()
  await expect(page.getByText('종결됨', { exact: true })).toBeVisible()

  // The customer: completed, the result, and the manual titles behind the analysis, never the AI text.
  await customer.page.goto(`/#/portal/${id}`)
  await customer.page.reload()
  await expect(customer.page.getByText('ATC 구동부를 점검하고 정상 동작을 확인했습니다.', { exact: false })).toBeVisible()
  await customer.page.goto(`/#/portal/${id}`)
  await customer.page.reload()
  await expect(customer.page.locator('.pd-meta').getByText('완료', { exact: true })).toBeVisible()
  const guidesTab = customer.page.getByRole('tab', { name: '기술 가이드', exact: true })
  await guidesTab.click()
  await guidesTab.hover()  // the pointer stays on the tab it just chose; its label must stay readable
  const tabColors = await guidesTab.evaluate(el => { const s = getComputedStyle(el); return [s.color, s.backgroundColor] })
  expect(tabColors[0], 'selected tab text vs background').not.toBe(tabColors[1])
  expect(tabColors[1], 'selected tab keeps its selected background while hovered').toBe(await guidesTab.evaluate(el => getComputedStyle(el).borderTopColor))
  await expect(customer.page.getByText('E2E 매뉴얼', { exact: true })).toBeVisible()
  await expect(customer.page.getByText('AI가 접수 내용을 바탕으로 찾은 자료입니다.', { exact: false })).toBeVisible()
  await customer.page.getByRole('button', { name: '원본 페이지 보기', exact: true }).click()
  const guide = customer.page.getByRole('dialog', { name: /원본 페이지 · E2E 매뉴얼/ })
  await expect(guide.getByRole('img')).toBeVisible()
  expect(await guide.getByRole('img').evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true)
  await customer.page.keyboard.press('Escape')
  const pageApi = `/api/v1/service-requests/${id}/evidence/E1/page`
  const opened = await customer.page.request.get(pageApi)
  expect(opened.status()).toBe(200)
  expect(opened.headers()['content-type']).toBe('image/png')
  expect((await customer.page.request.get(`/api/v1/service-requests/${id}/evidence/E2/page`)).status()).toBe(404)  // cases are not guides
  const seen = JSON.stringify(await serverItem(customer.page, id))
  for (const secret of ['ATC 구동부 점검 절차', 'E2E 통제된 분석 응답', '부품 수배']) expect(seen).not.toContain(secret)
  expect(customer.errors.concat(staff.errors)).toEqual([])
  await closeAll(customer, staff)
})

// ---------------------------------------------------------------------------------------------------------------
// Narrow screens and failures
// ---------------------------------------------------------------------------------------------------------------

test('every screen fits a phone-sized viewport without sideways scrolling and keeps its main actions reachable', async ({ browser }) => {
  const phone = { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }
  const visitor = await browser.newContext(phone)
  const anon = await visitor.newPage()
  for (const hash of ['home', 'support', 'login', 'no-such-page']) {
    await anon.goto(`/#/${hash}`)
    await expect(anon.locator('main')).toBeVisible()
    expect(await overflowing(anon), `public ${hash}`).toEqual([])
  }
  await anon.goto('/#/home')
  await expect(anon.getByRole('link', { name: /^로그인/ }).first()).toBeInViewport()
  await visitor.close()

  const customer = await session(browser, process.env.E2E_CUSTOMER, 'portal', phone)
  const staff = await session(browser, process.env.E2E_STAFF, 'cases', phone)
  const id = await createRequest(customer.page, { message: '모바일 화면 확인용 요청입니다.' })
  expect(await overflowing(customer.page), 'customer detail').toEqual([])
  await customer.page.goto('/#/portal')
  await expect(rowFor(customer.page, id)).toBeAttached()
  expect(await overflowing(customer.page), 'customer list').toEqual([])
  await customer.page.goto('/#/portal/new')
  await expect(customer.page.getByRole('button', { name: '전송', exact: true })).toBeVisible()
  await customer.page.getByRole('button', { name: '전송', exact: true }).scrollIntoViewIfNeeded()
  expect(await overflowing(customer.page), 'intake form').toEqual([])
  await customer.page.keyboard.press('Escape')

  await analyse(staff.page, id)
  expect(await overflowing(staff.page), 'operator detail').toEqual([])
  // The AI notice is long; it must wrap below the heading instead of squeezing "AI 분석" onto two lines.
  const aiHeading = staff.page.getByRole('heading', { name: 'AI 분석' })
  const lines = await aiHeading.evaluate(h => Math.round(h.getBoundingClientRect().height / parseFloat(getComputedStyle(h).lineHeight)))
  expect(lines, 'AI 분석 heading lines').toBe(1)
  for (const hash of ['cases', 'departments']) {
    await staff.page.goto(`/#/${hash}`)
    await expect(staff.page.locator('main')).toBeVisible()
    expect(await overflowing(staff.page), `operator ${hash}`).toEqual([])
  }
  expect(customer.errors.concat(staff.errors)).toEqual([])
  await closeAll(customer, staff)
})

test('(network stub) a failing request list is reported and can be retried; a lost session returns to sign-in', async ({ browser }) => {
  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const { page } = staff
  // Opening another screen loads the list again (navigating to the same address would not).
  await page.route('**/api/v1/service-requests', route => route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"stub failure"}' }))
  await page.reload()
  await expect(page.getByRole('heading', { name: '요청을 불러오지 못했습니다' })).toBeVisible()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.unroute('**/api/v1/service-requests')
  await page.getByRole('button', { name: '다시 시도', exact: true }).click()
  await expect(page.getByRole('complementary', { name: '대기열' })).toBeVisible()

  // The session is lost while the list loads: back to sign-in.
  await page.route('**/api/v1/service-requests', route => route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"stub failure"}' }))
  await page.reload()
  await expect(page.getByRole('heading', { name: '요청을 불러오지 못했습니다' })).toBeVisible()
  await page.unroute('**/api/v1/service-requests')
  await page.route('**/api/v1/service-requests', route => route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"expired"}' }))
  await page.getByRole('button', { name: '다시 시도', exact: true }).click()
  await expect(page).toHaveURL(/#\/login$/)
  expect(staff.errors).toEqual([])
  await closeAll(staff)
})
