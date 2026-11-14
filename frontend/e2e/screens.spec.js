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
  await page.getByRole('combobox', { name: '기계 · 호기 *', exact: true }).selectOption({ index: 1 })
}

// Customer intake through the real form. `portal` false = the operator's own "새 요청" modal.
async function createRequest(page, { reason = '기계 고장', message, name = '접수 담당자', phone = '010-0000-0000', portal = true }) {
  await page.goto(portal ? '/#/portal/new' : '/#/cases/new')
  await page.getByRole('combobox', { name: '접수 사유 *', exact: true }).selectOption(reason)
  await chooseMachine(page)
  await page.getByLabel('메시지 *', { exact: true }).fill(message)
  await page.getByRole('button', { name: '계속', exact: true }).click()
  await page.getByLabel('이름 *', { exact: true }).fill(name)
  await page.getByLabel('전화번호 *', { exact: true }).fill(phone)
  const response = page.waitForResponse(r => r.url().endsWith(API) && r.request().method() === 'POST')
  await page.getByRole('button', { name: '전송', exact: true }).click()
  const created = await (await response).json()
  await expect(page).toHaveURL(new RegExp(`#/${portal ? 'portal' : 'cases'}/${created.id}$`))
  return created.id
}

const serverItem = async (page, id) => (await page.request.get(`${API}/${id}`)).json()
const statusButton = (page, name) => page.getByRole('button', { name: new RegExp(`^${name}`) })
const rowFor = (page, id) => page.getByRole('row').filter({ hasText: id })

async function analyse(staff, id, wanted = '검토 대기') {
  await staff.goto(`/#/cases/${id}`)
  await staff.getByRole('button', { name: 'AI 분석 시작', exact: true }).click()
  await expect(statusButton(staff, wanted)).toBeVisible({ timeout: PAGE_BUDGET })
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

  // Footer: AI notice and image credits.
  await expect(page.getByText('AI가 생성한 답변은 인용된 근거와 원본 매뉴얼을 함께 확인해 주세요.')).toBeVisible()
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
  await expect(page.getByRole('note', { name: 'AI 생성 콘텐츠 안내' })).toContainText('AI가 생성합니다')
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
  for (const hash of ['cases', 'cases/new', 'cases/CLM-001', 'portal', 'portal/new', 'portal/CLM-001', 'work', 'work/SVC-001']) {
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
  for (const hash of ['cases', 'cases/new', 'work', 'login']) {
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
  await ops.getByRole('link', { name: '받은 업무' }).click()
  await expect(staff.page).toHaveURL(/#\/work$/)
  await expect(ops.getByRole('link', { name: '받은 업무' })).toHaveAttribute('aria-current', 'page')
  await expect(staff.page.getByRole('navigation', { name: '고객 메뉴' })).toHaveCount(0)
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

test('intake form: required fields, two steps, alarm numbers, dismissal and no attachment upload', async ({ browser }) => {
  const customer = await session(browser, process.env.E2E_CUSTOMER, 'portal')
  const { page } = customer
  await page.goto('/#/portal/new')
  const dialog = page.getByRole('dialog', { name: '새 서비스 요청' })
  await expect(dialog).toBeVisible()

  // Attachments are not offered at all.
  await expect(dialog.locator('input[type="file"]')).toHaveCount(0)
  await expect(dialog).not.toContainText('첨부')
  await expect(dialog).not.toContainText('사진')

  const next = dialog.getByRole('button', { name: '계속', exact: true })
  await expect(next).toBeDisabled()
  await dialog.getByRole('combobox', { name: '접수 사유 *' }).selectOption('부품 문의')
  await expect(next).toBeDisabled()
  await chooseMachine(page)
  await expect(next).toBeDisabled()
  await dialog.getByLabel('메시지 *', { exact: true }).fill('   ')
  await expect(next).toBeDisabled()  // blank text does not count
  await dialog.getByLabel('메시지 *', { exact: true }).fill('부품 교체 시기를 알고 싶습니다. 입력 확인용')
  await expect(next).toBeEnabled()

  // Alarm numbers: add until the limit of 20.
  await dialog.getByLabel('오류 번호 1', { exact: true }).fill('2023')
  for (let count = 2; count <= 20; count += 1) await dialog.getByRole('button', { name: '+ 오류 번호 추가' }).click()
  await expect(dialog.getByRole('button', { name: '+ 오류 번호 추가' })).toBeDisabled()
  await expect(dialog.getByLabel('오류 번호 20', { exact: true })).toBeVisible()
  await dialog.getByLabel('오류 번호 2', { exact: true }).fill('2024')

  // Step 2 recaps step 1, needs a name and phone, and can go back without losing input.
  await next.click()
  await expect(dialog.getByRole('list', { name: '진행 단계' }).locator('li.on')).toContainText('연락처')
  await expect(dialog.getByText('부품 문의', { exact: true })).toBeVisible()
  await expect(dialog.getByText('부품 교체 시기를 알고 싶습니다. 입력 확인용')).toBeVisible()
  const send = dialog.getByRole('button', { name: '전송', exact: true })
  await expect(send).toBeDisabled()
  await dialog.getByLabel('이름 *', { exact: true }).fill('홍길동')
  await expect(send).toBeDisabled()
  await dialog.getByLabel('전화번호 *', { exact: true }).fill('010-1234-5678')
  await expect(send).toBeEnabled()
  await dialog.getByRole('button', { name: '이전', exact: true }).click()
  // A re-mounted textarea carries its text inside the label, so address it by role, not by exact label text.
  await expect(dialog.getByRole('textbox', { name: '메시지 *' })).toHaveValue('부품 교체 시기를 알고 싶습니다. 입력 확인용')
  await expect(dialog.getByLabel('오류 번호 1', { exact: true })).toHaveValue('2023')
  await next.click()
  await expect(dialog.getByLabel('이름 *', { exact: true })).toHaveValue('홍길동')

  // An invalid e-mail address is refused by the browser before anything is sent.
  let sent = 0
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith(API)) sent += 1 })
  await dialog.getByLabel('이메일', { exact: true }).fill('not-an-email')
  await send.click()
  await expect(page).toHaveURL(/#\/portal\/new$/)
  expect(sent).toBe(0)
  await dialog.getByLabel('이메일', { exact: true }).fill('hong@example.com')
  const response = page.waitForResponse(r => r.url().endsWith(API) && r.request().method() === 'POST')
  await send.click()
  const created = await (await response).json()
  await expect(page).toHaveURL(new RegExp(`#/portal/${created.id}$`))

  // What was typed is what was stored and what the customer sees again.
  const stored = await serverItem(page, created.id)
  expect(stored.intake.type).toBe('부품 문의')
  expect(stored.intake.alarm).toContain('2023')
  expect(stored.intake.alarm).toContain('2024')
  expect(stored.intake.contact).toMatchObject({ name: '홍길동', phone: '010-1234-5678', email: 'hong@example.com' })
  await expect(page.getByText('부품 교체 시기를 알고 싶습니다. 입력 확인용').first()).toBeVisible()
  await page.getByRole('tab', { name: '연락처', exact: true }).click()
  const contact = page.getByRole('tabpanel')
  await expect(contact.getByText('홍길동')).toBeVisible()
  await expect(contact.getByText('010-1234-5678')).toBeVisible()
  await expect(contact.getByText('hong@example.com')).toBeVisible()

  // Dismissal never submits: Escape, the close button and a click outside.
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
  await expect(dialog.getByRole('status')).toContainText('접수할 수 있는 등록 장비가 없습니다')
  await expect(dialog.getByRole('combobox', { name: '기계 · 호기 *' })).toBeDisabled()
  await expect(dialog.getByRole('button', { name: '계속', exact: true })).toBeDisabled()
  const forced = await nobody.page.request.post(API, {
    headers: { Origin: new URL(nobody.page.url()).origin, 'X-CSRF-Token': (await (await nobody.page.request.get('/api/v1/auth/me')).json()).csrf_token },
    data: { equipment_id: '00000000-0000-0000-0000-000000000000', reason: '기계 고장', message: 'x', alarm_numbers: [], contact: { name: 'n', phone: '1' } } })
  expect(forced.status()).toBeGreaterThanOrEqual(400)
  await closeAll(nobody)

  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(staff.page, { message: '운영진이 대신 접수한 요청입니다.', name: '운영 접수', portal: false })
  await expect(staff.page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(staff.page.getByRole('button', { name: 'AI 분석 시작', exact: true })).toBeVisible()
  await expect(staff.page.getByText('운영진이 대신 접수한 요청입니다.').first()).toBeVisible()
  expect((await serverItem(staff.page, id)).status).toBe('접수됨')
  await staff.page.goto('/#/cases/new')
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
  const first = await createRequest(alice.page, { reason: '기계 고장', message: '목록 확인 첫째 요청', name: '앨리스 담당' })
  const second = await createRequest(colleague.page, { reason: '기술 문의', message: '목록 확인 둘째 요청', name: '동료 담당' })
  const foreign = await createRequest(bob.page, { reason: '기계 고장', message: '다른 회사의 요청', name: '밥 담당' })
  await analyse(staff.page, first)

  // The whole company sees the same requests; another company sees none of them.
  await alice.page.goto('/#/portal')
  for (const id of [first, second]) await expect(rowFor(alice.page, id)).toBeVisible()
  await expect(rowFor(alice.page, foreign)).toHaveCount(0)
  await bob.page.goto('/#/portal')
  await expect(rowFor(bob.page, foreign)).toBeVisible()
  await expect(rowFor(bob.page, first)).toHaveCount(0)
  await expect(alice.page.getByText('의 서비스 요청을 한곳에서 확인합니다.', { exact: false })).toBeVisible()

  // Internal status names never reach the customer: an analysed request is simply "확인 중".
  await expect(rowFor(alice.page, first).getByText('확인 중', { exact: true })).toBeVisible()
  await expect(rowFor(alice.page, second).getByText('접수됨', { exact: true })).toBeVisible()
  await expect(alice.page.getByText('검토 대기', { exact: true })).toHaveCount(0)

  const page = alice.page
  const total = page.getByText(/^총 \d+건$/)
  // Status filter + removable chip.
  await page.getByRole('combobox', { name: '상태', exact: true }).selectOption('확인 중')
  await expect(rowFor(page, first)).toBeVisible()
  await expect(rowFor(page, second)).toHaveCount(0)
  await page.getByRole('button', { name: '상태: 확인 중 ×' }).click()
  await expect(rowFor(page, second)).toBeVisible()
  // Type filter.
  await page.getByRole('combobox', { name: '유형', exact: true }).selectOption('기술 문의')
  await expect(rowFor(page, second)).toBeVisible()
  await expect(rowFor(page, first)).toHaveCount(0)
  await page.getByRole('button', { name: '유형: 기술 문의 ×' }).click()
  // Creator filter (options are the people who filed).
  await page.getByRole('combobox', { name: '접수자', exact: true }).selectOption({ label: await optionWith(page.getByRole('combobox', { name: '접수자', exact: true }), '동료 담당') })
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

  // Detail: facts, history, guides (none before approval), contact, and the three customer actions.
  await page.getByRole('link', { name: `${first} 상세 보기` }).click()
  await expect(page).toHaveURL(new RegExp(`#/portal/${first}$`))
  const facts = page.locator('.pd-meta')
  await expect(facts).toContainText(first)
  await expect(facts).toContainText('앨리스 담당')
  await expect(facts.getByText('확인 중', { exact: true })).toBeVisible()
  await expect(page.getByText('목록 확인 첫째 요청').first()).toBeVisible()
  await expect(page.getByRole('tab', { name: '이력', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('heading', { name: '요청 이력' })).toBeVisible()
  await page.getByRole('tab', { name: '기술 가이드', exact: true }).click()
  await expect(page.getByText('해당하는 기술 가이드가 아직 없습니다.', { exact: false })).toBeVisible()
  await page.getByRole('tab', { name: '연락처', exact: true }).click()
  await expect(page.getByRole('tabpanel').getByText('앨리스 담당')).toBeVisible()
  await expect(page.getByText('회사의 모든 직원이 이 요청을 확인할 수 있습니다.', { exact: false })).toBeVisible()
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
  const analysed = await createRequest(alice.page, { reason: '기계 고장', message: '대기열 확인 분석 대상', name: '큐 앨리스' })
  const waiting = await createRequest(colleague.page, { reason: '교육·기술지원', message: '대기열 확인 접수 대상', name: '큐 동료' })
  const page = staff.page
  await page.reload()  // the list loaded at sign-in predates the two requests filed above
  const side = page.getByRole('complementary', { name: '대기열' })
  const count = async name => Number((await side.getByRole('button', { name: new RegExp(`^${name}`) }).locator('.count').textContent()).trim())
  const before = await count('검토 대기')
  const beforeNew = await count('접수됨')
  await analyse(page, analysed)
  await page.goto('/#/cases')
  await page.reload()
  expect(await count('검토 대기')).toBe(before + 1)
  expect(await count('접수됨')).toBe(beforeNew - 1)  // the analysed request left "접수됨"
  const all = await count('모든 요청')
  await expect(page.getByText(`총 ${all}건`)).toBeVisible()
  expect(all).toBeGreaterThanOrEqual(2)

  // Queue buttons filter by status and mark the current one.
  await side.getByRole('button', { name: /^검토 대기/ }).click()
  await expect(side.getByRole('button', { name: /^검토 대기/ })).toHaveAttribute('aria-current', 'true')
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
  await page.getByRole('combobox', { name: '접수자', exact: true }).selectOption({ label: await optionWith(page.getByRole('combobox', { name: '접수자', exact: true }), '큐 동료') })
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
  const id = await createRequest(customer.page, { message: 'ATC 교환 중 정지합니다. 화면 점검용.', name: '상세 점검' })
  const page = staff.page
  await page.goto(`/#/cases/${id}`)

  // Before analysis: nothing is pretended.
  await expect(page.getByText('아직 분석 결과가 없습니다.')).toBeVisible()
  await expect(page.getByText('미분석', { exact: true })).toBeVisible()
  await expect(page.getByText('아직 분석 결과와 부서별 초안이 없습니다.', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: '검토 전' })).toBeVisible()
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
  await expect(page.getByText('AI를 사용합니다. 결과를 확인해 주세요.', { exact: false })).toBeVisible()

  // Tab 1: causes with their sources, steps and open questions.
  await expect(page.getByRole('tab', { name: '문제 해결 단계', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('heading', { name: '추정 원인' })).toBeVisible()
  await expect(page.getByText('ATC 암 구동 불량', { exact: true })).toBeVisible()
  await expect(page.getByText('가능성 높음', { exact: true })).toBeVisible()
  await expect(page.getByText('출처: E2E 매뉴얼 p.45 · FSR-00001 · VMCT-05')).toBeVisible()
  await expect(page.getByText('알람 이력 확인', { exact: true })).toBeVisible()
  await expect(page.getByText('정지 위치를 알려주세요.', { exact: true })).toBeVisible()
  // Tab 2: past cases; the excerpt opens and closes and carries its caution.
  await page.getByRole('tab', { name: '과거 정비 이력', exact: true }).click()
  await expect(page.getByRole('heading', { name: '유사 과거 사례 1건' })).toBeVisible()
  const fsr = page.getByRole('button', { name: /FSR-00001/ })
  await expect(fsr).toHaveAttribute('aria-expanded', 'false')
  await fsr.click()
  await expect(fsr).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('공구 교환 중 정지', { exact: true })).toBeVisible()
  await expect(page.getByText('적용 시 주의: 과거 사례는 참고용입니다.', { exact: false })).toBeVisible()
  await fsr.click()
  await expect(page.getByText('공구 교환 중 정지', { exact: true })).toHaveCount(0)
  // Tab 3: parts. Tab 4: manuals.
  await page.getByRole('tab', { name: '권장 부품', exact: true }).click()
  await expect(page.getByText('ATC 암 모터', { exact: true })).toBeVisible()
  await expect(page.getByText('출처: E2E 매뉴얼 p.45')).toBeVisible()
  await page.getByRole('tab', { name: '매뉴얼 열람', exact: true }).click()
  await expect(page.getByRole('heading', { name: '관련 매뉴얼 1건' })).toBeVisible()
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

  // The AI summary can be copied into an internal note; customers never see it.
  await page.getByRole('button', { name: '내부 메모로 복사' }).click()
  await expect(page.locator('li.comment.internal')).toContainText('E2E 통제된 분석 응답')
  await expect(page.locator('li.comment.internal')).toContainText('내부 메모')
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('E2E 통제된 분석 응답')

  // Activity: filters between everything, comments and history; an empty note cannot be saved; cancel discards.
  const activity = page.getByRole('region', { name: '활동' })
  await activity.getByRole('tab', { name: '이력', exact: true }).click()
  await expect(activity.locator('li.event').first()).toBeVisible()
  await expect(activity.locator('li.comment')).toHaveCount(0)
  await activity.getByRole('tab', { name: '댓글', exact: true }).click()
  await expect(activity.locator('li.event')).toHaveCount(0)
  await expect(activity.locator('li.comment')).toHaveCount(1)
  await activity.getByRole('tab', { name: '전체', exact: true }).click()
  await activity.getByRole('button', { name: '내부 메모 추가', exact: true }).click()
  await expect(activity.getByRole('button', { name: '저장', exact: true })).toBeDisabled()
  await activity.getByLabel('내부 메모', { exact: true }).fill('저장하지 않을 메모')
  await activity.getByRole('button', { name: '취소', exact: true }).click()
  await expect(activity.getByLabel('내부 메모', { exact: true })).toHaveCount(0)
  await expect(page.getByText('저장하지 않을 메모')).toHaveCount(0)

  // Department proposals: AI choice, adding, excluding, empty drafts, edit marker and reset to the AI original.
  await expect(page.getByRole('heading', { name: '연결 업무 제안' })).toBeVisible()
  await expect(page.getByText('승인 전 · 아직 전달되지 않음')).toBeVisible()
  const service = page.getByRole('checkbox', { name: /^서비스/ })
  const quality = page.getByRole('checkbox', { name: /^품질/ })
  await expect(service).toBeChecked()
  await expect(page.getByText('AI 추천', { exact: true })).toBeVisible()
  await expect(quality).not.toBeChecked()
  const approve = page.getByRole('button', { name: '승인', exact: true })
  await expect(approve).toBeEnabled()
  await quality.click()
  await expect(page.getByText('추가함', { exact: true })).toBeVisible()
  await expect(page.getByText('초안이 비어 있습니다.')).toBeVisible()
  await expect(approve).toBeDisabled()
  await expect(page.getByText('부서를 한 곳 이상 선택하고 모든 초안을 채우면 승인할 수 있습니다.')).toBeVisible()
  await quality.click()
  await expect(quality).not.toBeChecked()
  await expect(approve).toBeEnabled()
  await service.click()
  await expect(page.getByText('제외함', { exact: true })).toBeVisible()
  await expect(approve).toBeDisabled()
  await service.click()
  await expect(service).toBeChecked()
  const draft = page.getByLabel('서비스 초안', { exact: true })
  await expect(draft).toHaveValue('ATC 점검 방문 초안')
  await draft.fill('검토자가 바꾼 초안')
  await expect(page.getByRole('button', { name: /초안 접기 · 수정됨/ })).toBeVisible()
  await page.getByRole('button', { name: 'AI 원본으로 되돌리기' }).click()
  await expect(draft).toHaveValue('ATC 점검 방문 초안')
  await page.getByRole('button', { name: /^초안 접기/ }).click()
  await expect(draft).toHaveCount(0)
  await page.getByRole('button', { name: /^초안 보기/ }).click()
  await expect(draft).toBeVisible()

  // Details panel, status menu and decline form can be opened and left without side effects.
  await expect(page.getByText('대상 부서')).toBeVisible()
  await page.getByRole('button', { name: '나에게 지정', exact: true }).click()
  await expect(page.locator('.detail-list')).toContainText(process.env.E2E_STAFF)
  const status = statusButton(page, '검토 대기')
  await status.click()
  await expect(page.getByRole('menuitem', { name: '재분석 요청', exact: true })).toBeEnabled()
  await status.click()
  await expect(page.getByRole('menu')).toHaveCount(0)
  await page.getByRole('button', { name: '반려', exact: true }).click()
  await expect(page.getByRole('button', { name: '반려 확인', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '취소', exact: true }).last().click()
  await expect(page.getByRole('button', { name: '반려 확인', exact: true })).toHaveCount(0)
  expect((await serverItem(page, id)).status).toBe('검토 대기')
  expect(customer.errors.concat(staff.errors)).toEqual([])
  await closeAll(customer, staff)
})

test('four-team approval, department inbox, work detail and what the customer sees from guides', async ({ browser }) => {
  const customer = await session(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await session(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, { message: '네 부서 승인 확인용 요청입니다.', name: '부서 확인' })
  const number = id.slice(4)
  const keys = { service: `SVC-${number}`, quality: `QLT-${number}`, parts: `PRT-${number}`, sales: `SAL-${number}` }
  const page = staff.page
  await analyse(page, id)
  // Before approval a customer cannot open the page, and the refusal looks like "does not exist".
  expect((await customer.page.request.get(`/api/v1/service-requests/${id}/evidence/E1/page`)).status()).toBe(404)
  for (const [department, draft] of [['품질', '품질 지시'], ['부품·자재', '부품 지시'], ['영업', '영업 지시']]) {
    await page.getByRole('checkbox', { name: new RegExp(`^${department}`) }).click()
    await page.getByLabel(`${department} 초안`, { exact: true }).fill(draft)
  }
  await page.getByRole('button', { name: '승인', exact: true }).click()
  await expect(statusButton(page, '처리 중')).toBeVisible()
  await expect(page.getByText('0/4 완료', { exact: false }).first()).toBeVisible()
  const approved = await serverItem(page, id)
  expect(approved.linked.map(work => work.workKey)).toEqual([keys.service, keys.quality, keys.parts, keys.sales])
  await expect(page.getByText('승인한 내용만 연결 업무로 생성되며, 승인 후에는 수정할 수 없습니다.')).toBeVisible()
  await expect(page.getByRole('checkbox')).toHaveCount(0)  // proposals are no longer editable

  // Each team sees exactly its own work.
  await page.goto('/#/work')
  const team = page.locator('.team-select select')
  const queue = page.getByRole('complementary', { name: '업무 큐' })
  for (const [label, department] of [['서비스팀', 'service'], ['품질팀', 'quality'], ['부품·자재팀', 'parts'], ['영업팀', 'sales']]) {
    await team.selectOption({ label })
    await expect(page.getByRole('heading', { name: `${label} 받은 업무` })).toBeVisible()
    await expect(rowFor(page, keys[department])).toBeVisible()
    for (const [other, key] of Object.entries(keys)) if (other !== department) await expect(page.getByRole('link', { name: key, exact: true })).toHaveCount(0)
  }
  await team.selectOption({ label: '서비스팀' })
  await queue.getByRole('button', { name: /^진행 중/ }).click()
  await expect(rowFor(page, keys.service)).toHaveCount(0)
  await queue.getByRole('button', { name: /^전달됨/ }).click()
  await expect(rowFor(page, keys.service)).toBeVisible()
  await queue.getByRole('button', { name: /^완료/ }).click()
  await expect(rowFor(page, keys.service)).toHaveCount(0)

  // Work detail: instructions, original request, AI summary, siblings, claiming, starting and finishing.
  await page.goto(`/#/work/${keys.parts}`)
  await expect(page.getByText('품질 담당자 승인 완료')).toBeVisible()
  await expect(page.getByText('부품 지시', { exact: true })).toBeVisible()
  await expect(page.getByText('네 부서 승인 확인용 요청입니다.').first()).toBeVisible()
  await expect(page.getByText('E2E 통제된 분석 응답', { exact: false })).toBeVisible()
  const siblings = page.locator('.siblings')
  for (const other of [keys.service, keys.quality, keys.sales]) await expect(siblings).toContainText(other)
  await expect(siblings).not.toContainText(keys.parts)
  await expect(page.getByText('처리를 시작하면 결과를 입력할 수 있습니다.')).toBeVisible()
  await page.getByRole('button', { name: '나에게 지정', exact: true }).click()
  await expect(page.locator('.detail-list')).toContainText(process.env.E2E_STAFF)
  await page.getByRole('button', { name: '처리 시작', exact: true }).click()
  await expect(page.locator('.status-btn')).toHaveText('진행 중')
  const finish = page.getByRole('button', { name: '처리 완료', exact: true })
  await expect(finish).toBeDisabled()
  await page.getByLabel('조치 내용 *', { exact: true }).fill('   ')
  await expect(finish).toBeDisabled()
  await page.getByLabel('조치 내용 *', { exact: true }).fill('부품 수배 완료')
  await finish.click()
  await expect(page.getByText('부품 수배 완료').first()).toBeVisible()
  await expect(page.getByText('작업 시간 미입력', { exact: false })).toBeVisible()
  await expect(page.locator('.status-btn')).toHaveText('완료')
  await expect(page.getByRole('button', { name: '처리 시작', exact: true })).toHaveCount(0)
  // The original request reflects it; closing stays blocked until every team is done.
  await page.goto(`/#/cases/${id}`)
  await expect(page.getByText('1/4 완료', { exact: false }).first()).toBeVisible()
  await expect(page.getByText('부서 업무가 모두 완료되면 종결할 수 있습니다.')).toBeVisible()
  await expect(page.getByRole('button', { name: '요청 종결', exact: true })).toHaveCount(0)
  // An unknown work key is explained.
  await page.goto('/#/work/SVC-999999')
  await expect(page.getByRole('heading', { name: '업무를 찾을 수 없습니다' })).toBeVisible()
  await page.getByRole('link', { name: '받은 업무로' }).click()
  await expect(page).toHaveURL(/#\/work$/)

  // Customer: progress and the manual titles behind the approved analysis, never the work or the AI text.
  await customer.page.goto(`/#/portal/${id}`)
  await customer.page.reload()
  await expect(customer.page.locator('.pd-meta').getByText('처리 중', { exact: true })).toBeVisible()
  await customer.page.getByRole('tab', { name: '기술 가이드', exact: true }).click()
  await expect(customer.page.getByText('E2E 매뉴얼', { exact: true })).toBeVisible()
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
  for (const secret of ['부품 지시', '영업 지시', keys.parts, 'ATC 구동부 점검 절차', 'E2E 통제된 분석 응답']) expect(seen).not.toContain(secret)
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
  const id = await createRequest(customer.page, { message: '모바일 화면 확인용 요청입니다.', name: '모바일' })
  expect(await overflowing(customer.page), 'customer detail').toEqual([])
  await customer.page.goto('/#/portal')
  await expect(rowFor(customer.page, id)).toBeAttached()
  expect(await overflowing(customer.page), 'customer list').toEqual([])
  await customer.page.goto('/#/portal/new')
  await expect(customer.page.getByRole('button', { name: '계속', exact: true })).toBeVisible()
  await customer.page.getByRole('button', { name: '계속', exact: true }).scrollIntoViewIfNeeded()
  expect(await overflowing(customer.page), 'intake form').toEqual([])
  await customer.page.keyboard.press('Escape')

  await analyse(staff.page, id)
  expect(await overflowing(staff.page), 'operator detail').toEqual([])
  await expect(staff.page.getByRole('button', { name: '승인', exact: true })).toBeAttached()
  for (const hash of ['cases', 'work']) {
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
  await page.goto('/#/work')
  await expect(page.getByRole('heading', { name: '요청을 불러오지 못했습니다' })).toBeVisible()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.unroute('**/api/v1/service-requests')
  await page.getByRole('button', { name: '다시 시도', exact: true }).click()
  await expect(page.getByRole('heading', { name: /받은 업무$/ })).toBeVisible()

  await page.route('**/api/v1/service-requests', route => route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"expired"}' }))
  await page.goto('/#/cases')
  await expect(page).toHaveURL(/#\/login$/)
  expect(staff.errors).toEqual([])
  await closeAll(staff)
})
