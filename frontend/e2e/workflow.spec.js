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
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/service-requests') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '전송', exact: true }).click()
  const created = await (await response).json()
  await expect(page).toHaveURL(new RegExp(`#/portal/${created.id}$`))
  return created.id
}

async function analyse(staff, id) {
  await staff.goto(`/#/cases/${id}`)
  await staff.getByRole('button', { name: '분석 시작', exact: true }).click()
  await expect(staff.getByText('분석 중입니다.', { exact: false })).toBeVisible()
}

const noFollowUp = page => Promise.all(['정보 추가', '콜백 요청', '종결 요청'].map(name =>
  expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)))

const statusBadge = (page, name) => page.getByRole('status', { name: `상태 ${name}` })
// The analysis is finished once the conversation opens (a request is 처리 중 from the moment it starts).
const analysisDone = page => expect(page.getByLabel('질문 입력', { exact: true })).toBeEnabled({ timeout: 15000 })
const serverItem = async (page, id) => (await page.request.get(`/api/v1/service-requests/${id}`)).json()

test('starting the analysis makes the request processing; the operator closes it with a result the customer reads', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, 'ATC 교환 중 정지합니다. 처리 흐름 확인.')

  // Before the analysis: received, only the start button, nothing else to review or close.
  await staff.page.goto(`/#/cases/${id}`)
  await expect(statusBadge(staff.page, '접수됨')).toBeVisible()
  await expect(staff.page.getByRole('button', { name: '분석 시작', exact: true })).toBeVisible()
  await expect(staff.page.getByText('연결 업무', { exact: true })).toHaveCount(0)
  await expect(staff.page.getByRole('button', { name: '요청 종결', exact: true })).toHaveCount(0)
  await expect(staff.page.getByRole('button', { name: '승인', exact: true })).toHaveCount(0)
  await expect(staff.page.getByText('담당자', { exact: true })).toHaveCount(0)

  // Starting the analysis is what makes it 처리 중, for the customer too.
  await staff.page.getByRole('button', { name: '분석 시작', exact: true }).click()
  await expect(statusBadge(staff.page, '처리 중')).toBeVisible()
  await analysisDone(staff.page)
  await expect(staff.page.getByText('E2E 통제된 분석 응답', { exact: false })).toBeVisible()
  await expect(staff.page.getByRole('button', { name: '재분석', exact: true })).toBeVisible()  // the rest appears after the analysis
  await customer.page.reload()
  await expect(customer.page.getByText('처리 중', { exact: true }).first()).toBeVisible()
  await expect(customer.page.getByText('담당부서에서 처리를 시작했습니다.', { exact: true })).toBeVisible()
  await expect(customer.page.getByText('E2E 통제된 분석 응답', { exact: false })).toHaveCount(0)
  await expect(customer.page.getByRole('tab', { name: '기술 가이드', exact: true })).toHaveCount(0)
  await expect(customer.page.getByText('E2E 매뉴얼', { exact: true })).toHaveCount(0)

  // Closing publishes the operator's result only.
  const close = staff.page.getByRole('button', { name: '요청 종결', exact: true })
  await expect(close).toBeDisabled()
  await staff.page.getByLabel('처리 결과 (고객에게 보입니다)', { exact: true }).fill('점검 결과를 안내드렸습니다.')
  await close.click()
  await expect(statusBadge(staff.page, '종결')).toBeVisible()
  await expect(staff.page.getByText('종결됨', { exact: true })).toBeVisible()
  await staff.page.reload()
  await expect(staff.page.getByText('종결됨', { exact: true })).toBeVisible()
  expect((await serverItem(staff.page, id)).status).toBe('종결')
  // A closed request is read-only: the history stays, nothing new can be asked, mailed or written.
  await expect(staff.page.getByRole('log', { name: 'AI 대화 내용' }).getByText('E2E 통제된 분석 응답', { exact: false })).toBeVisible()
  await expect(staff.page.getByLabel('질문 입력', { exact: true })).toBeDisabled()
  await expect(staff.page.getByRole('button', { name: '메일 작성', exact: true })).toHaveCount(0)
  await expect(staff.page.getByRole('button', { name: '재분석', exact: true })).toHaveCount(0)

  await customer.page.reload()
  await expect(customer.page.getByText('이 서비스 요청은 완료되었습니다.', { exact: false })).toBeVisible()
  await expect(customer.page.getByText('점검 결과를 안내드렸습니다.', { exact: false })).toBeVisible()
  await expect(customer.page.getByRole('tab', { name: '기술 가이드', exact: true })).toHaveCount(0)
  await expect(customer.page.getByText('E2E 매뉴얼', { exact: true })).toHaveCount(0)
  expect(await serverItem(customer.page, id)).not.toHaveProperty('guides')
  await noFollowUp(customer.page)  // a finished request offers nothing to do
  await customer.context.close()
  await staff.context.close()
})

test('a failed analysis leaves the request processing and can be retried', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_COLLEAGUE, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '분석실패 확인용 요청입니다.')
  await analyse(staff.page, id)
  await expect(staff.page.getByText('분석에 실패했습니다.', { exact: false })).toBeVisible({ timeout: 15000 })
  await expect(statusBadge(staff.page, '처리 중')).toBeVisible()
  await expect(staff.page.getByLabel('질문 입력', { exact: true })).toHaveCount(0)  // still no analysis to talk about
  expect((await serverItem(staff.page, id)).analysisRun.status).toBe('failed')
  await customer.page.reload()
  await expect(customer.page.getByText('처리 중', { exact: true }).first()).toBeVisible()
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('analysisRun')

  await staff.page.getByRole('button', { name: '분석 다시 시도', exact: true }).click()
  await analysisDone(staff.page)
  await expect(staff.page.getByText('E2E 통제된 분석 응답', { exact: false })).toBeVisible()
  await expect(staff.page.getByText('분석에 실패했습니다.', { exact: false })).toHaveCount(0)
  await customer.context.close()
  await staff.context.close()
})

test('insufficient evidence: operators can re-analyse the original request without saving facts', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '근거부족 증상 설명입니다.')
  await analyse(staff.page, id)
  await analysisDone(staff.page)
  await expect(staff.page.getByText('E2E 근거 부족 응답', { exact: false })).toBeVisible()
  // The AI's questions are for the operator, who gathers the answers outside the app.
  await expect(staff.page.getByRole('heading', { name: '운영진이 확인할 사항', exact: true })).toBeVisible()
  await expect(staff.page.getByText('알람 번호를 알려주세요.', { exact: false })).toBeVisible()

  // The customer is asked nothing: the request just reads as being checked.
  await customer.page.reload()
  await expect(customer.page.getByText('처리 중', { exact: true }).first()).toBeVisible()
  await expect(customer.page.getByText('정보 요청', { exact: true })).toHaveCount(0)
  await expect(customer.page.getByText('서비스 담당자가 추가 정보를 요청했습니다.', { exact: false })).toHaveCount(0)
  await expect(customer.page.getByText('알람 번호를 알려주세요.', { exact: false })).toHaveCount(0)
  await noFollowUp(customer.page)

  // No fact-saving input, proposal, list, or server endpoint remains.
  await expect(staff.page.getByLabel('추가 정보 입력', { exact: true })).toHaveCount(0)
  await expect(staff.page.getByRole('region', { name: '추가 정보 저장 제안' })).toHaveCount(0)
  await expect(staff.page.getByRole('list', { name: '운영진이 입력한 추가 정보' })).toHaveCount(0)
  expect(await serverItem(staff.page, id)).not.toHaveProperty('additionalInfo')
  const headers = { Origin: new URL(staff.page.url()).origin, 'X-CSRF-Token': (await (await staff.page.request.get('/api/v1/auth/me')).json()).csrf_token }
  expect([404, 405]).toContain((await staff.page.request.post(`/api/v1/service-requests/${id}/additional-info`, { headers, data: { text: '저장 금지' } })).status())
  await staff.page.getByRole('button', { name: '재분석', exact: true }).click()
  await expect(staff.page.getByText('분석 2회차', { exact: true })).toBeVisible({ timeout: 20000 })
  await customer.page.reload()
  await customer.context.close()
  await staff.context.close()
})

test('companies are isolated and customers cannot act on a request', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const other = await newContext(browser, process.env.E2E_OTHER_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '회사 격리 확인용입니다.')
  await noFollowUp(customer.page)

  // The internal conversation never reaches the customer's view.
  await analyse(staff.page, id)
  await analysisDone(staff.page)
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('E2E 통제된 분석 응답')
  // A different company can neither read it nor reach any action on it.
  const otherHeaders = { Origin: new URL(other.page.url()).origin, 'X-CSRF-Token': (await (await other.page.request.get('/api/v1/auth/me')).json()).csrf_token }
  expect((await other.page.request.get(`/api/v1/service-requests/${id}`)).status()).toBe(404)
  // A customer cannot call operator actions, and the old customer follow-up endpoints no longer exist.
  const customerHeaders = { Origin: new URL(customer.page.url()).origin, 'X-CSRF-Token': (await (await customer.page.request.get('/api/v1/auth/me')).json()).csrf_token }
  expect((await customer.page.request.post(`/api/v1/service-requests/${id}/resolution`, { headers: customerHeaders, data: { note: 'x' } })).status()).toBe(403)
  for (const suffix of ['replies', 'callback', 'close-request']) {
    expect([404, 405]).toContain((await customer.page.request.post(`/api/v1/service-requests/${id}/${suffix}`, { headers: customerHeaders, data: { text: 'x', reason: 'y' } })).status())
    expect([404, 405]).toContain((await other.page.request.post(`/api/v1/service-requests/${id}/${suffix}`, { headers: otherHeaders, data: { text: 'x', reason: 'y' } })).status())
  }
  await customer.context.close(); await other.context.close(); await staff.context.close()
})

test('the operator chat answers from tool results, shows evidence and keeps its history; customers have none', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, 'ATC가 작동하지 않습니다. 채팅 확인용 증상 설명입니다.')
  await staff.page.goto(`/#/cases/${id}`)
  await expect(staff.page.getByRole('heading', { name: 'AI 분석·대화', exact: true })).toBeVisible()

  // Before the first analysis the conversation is closed: only the start button works.
  await expect(staff.page.getByLabel('질문 입력', { exact: true })).toHaveCount(0)
  await expect(staff.page.getByRole('button', { name: '사례 담당자는?', exact: true })).toHaveCount(0)
  await expect(staff.page.getByRole('button', { name: '분석 시작', exact: true })).toBeEnabled()
  await staff.page.getByRole('button', { name: '분석 시작', exact: true }).click()
  await analysisDone(staff.page)
  await expect(staff.page.getByLabel('질문 입력', { exact: true })).toBeEnabled()
  await expect(staff.page.getByText('읽기 전용이며', { exact: false })).toBeVisible()

  await staff.page.getByRole('button', { name: '사례 담당자는?', exact: true }).click()
  const log = staff.page.getByRole('log', { name: 'AI 대화 내용' })
  await expect(log.getByText('이 요청과 비슷한 과거 사례를 찾아', { exact: false })).toBeVisible()
  await expect(log.getByText('비슷한 사례는 FSR-00005이며 담당 작업자는 EMP-0003입니다.', { exact: true })).toBeVisible({ timeout: 15000 })
  // Markdown is rendered, not shown raw: the bold case number is a real <strong>.
  await expect(log.locator('strong', { hasText: 'FSR-00005' }).first()).toBeVisible()
  await expect(log).not.toContainText('**')
  const trail = log.getByRole('list', { name: '조회 과정' }).getByRole('listitem')
  await expect(trail).toHaveText(['과거 사례 검색 · 완료', '사례 담당 기록 조회 · 완료', '매뉴얼 검색 · 완료'])
  const evidence = log.locator('.chat-evidence')  // the cards of this answer, apart from the analysis bubble above
  await expect(evidence.getByText('과거 사례 1건 (보기)', { exact: true })).toBeVisible()
  await expect(log.getByText('사례 담당 기록 1건', { exact: true })).toBeVisible()
  await expect(log.getByText('FSR-00005 · 작업자 EMP-0003 · 천안직영센터 · CENTER-003', { exact: true })).toBeVisible()
  await evidence.getByText('관련 문서 1건 (보기)', { exact: true }).click()
  await evidence.getByRole('button', { name: '원본 페이지 보기', exact: true }).click()
  const image = staff.page.getByRole('img', { name: 'E2E 매뉴얼 p.2-31 원본 페이지' })
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate((img) => img.complete && img.naturalWidth > 0), { timeout: 10000 }).toBe(true)  // really decoded
  await staff.page.keyboard.press('Escape')
  await expect(staff.page.getByText('질문 1/30', { exact: false })).toBeVisible()

  // The chat only reads: the request itself is unchanged.
  expect((await serverItem(staff.page, id)).status).toBe('처리 중')

  // History is kept by the server.
  await staff.page.reload()
  await expect(staff.page.getByRole('log', { name: 'AI 대화 내용' }).getByText('비슷한 사례는 FSR-00005이며 담당 작업자는 EMP-0003입니다.', { exact: true })).toBeVisible()
  await expect(staff.page.getByText('질문 1/30', { exact: false })).toBeVisible()

  // Customers have no chat, in the screen or in the API.
  await customer.page.goto(`/#/portal/${id}`)
  await expect(customer.page.getByText('AI 대화', { exact: false })).toHaveCount(0)
  expect((await customer.page.request.get(`/api/v1/service-requests/${id}/chat`)).status()).toBe(403)
  await customer.context.close()
  await staff.context.close()
})

test('a department mail is only a draft until the operator presses send, and the card shows what really happened', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '메일 카드 확인용 증상 설명입니다.')
  await analyse(staff.page, id)
  await analysisDone(staff.page)
  await staff.page.getByLabel('질문 입력', { exact: true }).fill('서비스 출동 요청 메일 초안 만들어 주세요')
  await staff.page.getByRole('button', { name: '보내기', exact: true }).click()
  const card = staff.page.getByRole('region', { name: '서비스 메일' })
  await expect(card).toBeVisible({ timeout: 15000 })
  await expect(card.getByText('초안 · 아직 보내지 않았습니다', { exact: true })).toBeVisible()
  await expect(card.getByText('받는 사람', { exact: true })).toBeVisible()
  await expect(card.getByText('hodob76@gmail.com', { exact: false })).toBeVisible()  // operators see who will receive it
  const before = await serverItem(staff.page, id)
  expect(before.mailDrafts.map(d => d.status)).toEqual(['draft'])

  await card.getByLabel('메일 제목', { exact: true }).fill('[출동 요청] ATC 정지 (수정)')
  await card.getByRole('button', { name: '보내기', exact: true }).click()
  await expect(card.getByText('발송됨', { exact: true })).toBeVisible({ timeout: 10000 })
  await expect(card.getByText('[출동 요청] ATC 정지 (수정)', { exact: true })).toBeVisible()
  const after = await serverItem(staff.page, id)
  expect(after.mailDrafts.map(d => d.status)).toEqual(['sent'])
  expect(after.history.some(h => h.text.startsWith('메일 발송 · 서비스'))).toBe(true)

  await customer.page.goto(`/#/portal/${id}`)
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('mailDrafts')
  await customer.context.close()
  await staff.context.close()
})

test('a recommended activity unfolds a mail form under it from a template; nothing is saved or sent until send is pressed', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '권장 활동 확인용 증상 설명입니다.')
  await analyse(staff.page, id)
  await expect(staff.page.getByRole('heading', { name: '권장 활동 1건' })).toBeVisible()
  const activities = staff.page.getByRole('list', { name: '권장 활동' })
  const form = activities.getByRole('region', { name: '서비스 메일 작성' })
  await expect(form).toHaveCount(0)
  await activities.getByRole('button', { name: '메일 작성', exact: true }).click()

  // It unfolds in place from the fixed template: no dialog, no question in the conversation, nothing stored.
  await expect(form).toBeVisible()
  await expect(staff.page.getByRole('dialog')).toHaveCount(0)
  await expect(form.getByLabel('메일 제목', { exact: true })).toHaveValue(new RegExp(`^\\[출동 요청\\] ${id} \\| F400`))
  await expect(form.getByLabel('메일 본문', { exact: true })).toHaveValue(/서비스맨 출동 점검을 요청드립니다[\s\S]*요청 번호: CLM-/)
  await expect(form.getByText('받는 사람', { exact: true })).toBeVisible()
  await expect(form.getByText('서비스 · hodob76@gmail.com', { exact: false })).toBeVisible()
  await expect(staff.page.getByRole('log', { name: 'AI 대화 내용' }).locator('.chat-msg.user')).toHaveCount(0)
  expect((await serverItem(staff.page, id)).mailDrafts).toEqual([])

  // The agent fills the same form on request; still nothing is saved.
  await form.getByRole('button', { name: 'AI로 작성', exact: true }).click()
  await expect(form.getByLabel('메일 제목', { exact: true })).toHaveValue('[출동 요청] AI 작성 제목', { timeout: 15000 })
  await expect(form.getByLabel('메일 본문', { exact: true })).toHaveValue(/AI가 작성한 본문입니다/)
  expect((await serverItem(staff.page, id)).mailDrafts).toEqual([])

  // Folding closes it without a trace; unfolding again starts from the template.
  await activities.getByRole('button', { name: '접기', exact: true }).click()
  await expect(form).toHaveCount(0)
  expect((await serverItem(staff.page, id)).mailDrafts).toEqual([])
  await activities.getByRole('button', { name: '메일 작성', exact: true }).click()
  await expect(form.getByLabel('메일 제목', { exact: true })).toHaveValue(new RegExp(`^\\[출동 요청\\] ${id}`))
  await form.getByLabel('메일 제목', { exact: true }).fill('[출동 요청] 직접 수정한 제목')
  await form.getByRole('button', { name: '보내기', exact: true }).click()
  await expect(form).toHaveCount(0, { timeout: 10000 })
  const card = staff.page.getByRole('region', { name: '서비스 메일' })
  await expect(card.getByText('발송됨', { exact: true })).toBeVisible()
  await expect(card.getByText('[출동 요청] 직접 수정한 제목', { exact: true })).toBeVisible()
  const sent = await serverItem(staff.page, id)
  expect(sent.mailDrafts.map(d => d.status)).toEqual(['sent'])
  expect(sent.history.some(h => h.text.startsWith('메일 발송 · 서비스'))).toBe(true)
  await customer.context.close()
  await staff.context.close()
})

test('analysis and conversation are one window: analysis is the first bubble and a re-analysis stacks a new one', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '한 창 확인용 증상 설명입니다.')
  await staff.page.goto(`/#/cases/${id}`)
  await expect(staff.page.getByRole('heading', { name: 'AI 분석·대화', exact: true })).toBeVisible()
  // One section only: there is no separate AI analysis box, and the start button lives in the conversation.
  await expect(staff.page.getByRole('heading', { name: 'AI 분석', exact: true })).toHaveCount(0)
  const log = staff.page.getByRole('log', { name: 'AI 대화 내용' })
  await expect(log.getByText('아직 분석 결과가 없습니다.', { exact: false })).toBeVisible()
  await staff.page.getByRole('button', { name: '분석 시작', exact: true }).click()
  await expect(log.getByText('E2E 통제된 분석 응답', { exact: false })).toBeVisible({ timeout: 15000 })
  await expect(staff.page.getByRole('button', { name: '분석 시작', exact: true })).toHaveCount(0)
  await expect(log.getByRole('heading', { name: '원인 후보' })).toBeVisible()
  await expect(log.getByRole('heading', { name: '권장 활동 1건' })).toBeVisible()
  await expect(log.getByText('과거 사례 1건 (보기)', { exact: true })).toBeVisible()
  await expect(log.getByText('관련 문서 1건 (보기)', { exact: true })).toBeVisible()

  // A question follows the analysis in the same log.
  await staff.page.getByRole('button', { name: '사례 담당자는?', exact: true }).click()
  await expect(log.getByText('비슷한 사례는 FSR-00005이며 담당 작업자는 EMP-0003입니다.', { exact: true })).toBeVisible({ timeout: 15000 })

  // A re-analysis adds a new bubble below; the first one folds into "이전 분석".
  await staff.page.getByRole('button', { name: '재분석', exact: true }).click()
  await expect(log.getByText('분석 2회차', { exact: true })).toBeVisible({ timeout: 20000 })
  await expect(log.getByText('이전 분석 (1회차) 보기', { exact: true })).toBeVisible()
  const order = await log.locator('.chat-msg').evaluateAll((nodes) => nodes.map((n) => (n.classList.contains('analysis') ? 'analysis' : n.classList.contains('user') ? 'user' : 'answer')))
  expect(order.filter((kind) => kind === 'analysis')).toHaveLength(2)
  expect(order.indexOf('user')).toBeGreaterThan(order.indexOf('analysis'))
  expect(order.lastIndexOf('analysis')).toBeGreaterThan(order.indexOf('user'))

  // The original page of an earlier analysis opens too, chosen by its revision.
  await log.getByText('이전 분석 (1회차) 보기', { exact: true }).click()
  const earlier = log.locator('details').filter({ hasText: '이전 분석 (1회차) 보기' }).first()
  await earlier.getByText('관련 문서 1건 (보기)', { exact: true }).click()
  await earlier.getByRole('button', { name: /E2E 매뉴얼/ }).click()
  const pageRequest = staff.page.waitForRequest((r) => r.url().includes('/evidence/E1/page?revision=1'))
  await earlier.getByRole('button', { name: '원본 페이지 보기', exact: true }).click()
  await pageRequest
  const original = staff.page.getByRole('dialog', { name: /원본 페이지 · E2E 매뉴얼/ })
  await expect(original.getByRole('img', { name: /원본 페이지/ })).toBeVisible()
  await expect.poll(() => original.getByRole('img').evaluate((img) => img.complete && img.naturalWidth > 0), { timeout: 10000 }).toBe(true)
  await staff.page.keyboard.press('Escape')

  // The conversation survives a reload in the same order, and customers get none of it.
  await staff.page.reload()
  await expect(staff.page.getByRole('log', { name: 'AI 대화 내용' }).getByText('분석 2회차', { exact: true })).toBeVisible()
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('analysisHistory')
  await customer.context.close()
  await staff.context.close()
})

test('operators edit the department mail addresses on a settings page; customers cannot open it', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  await staff.page.getByRole('link', { name: '부서 메일', exact: true }).click()
  await expect(staff.page.getByRole('heading', { name: '부서 메일 설정', exact: true })).toBeVisible()
  const service = staff.page.getByRole('listitem', { name: '서비스 부서' })
  const recipients = service.getByLabel('수신 주소 (한 줄에 하나)')
  await expect(recipients).toHaveValue('hodob76@gmail.com')
  const save = service.getByRole('button', { name: '저장', exact: true })
  await expect(save).toBeDisabled()  // nothing changed

  await recipients.fill('not-an-address')
  await expect(service.getByRole('alert')).toContainText('주소 형식이 올바르지 않습니다')
  await expect(save).toBeDisabled()

  await recipients.fill('Dispatch@Example.com\nsecond@example.com')
  await save.click()
  await expect(service.getByText('저장했습니다.', { exact: true })).toBeVisible()
  await expect(recipients).toHaveValue('dispatch@example.com\nsecond@example.com')
  await expect(service.getByText('마지막 변경', { exact: false })).toBeVisible()
  const listed = await (await staff.page.request.get('/api/v1/service-requests/departments/manage')).json()
  expect(listed.departments.find(d => d.key === 'service').recipients).toEqual(['dispatch@example.com', 'second@example.com'])

  // The new address is what a mail form shows.
  const id = await createRequest(customer.page, '부서 주소 확인용 증상 설명입니다.')
  await analyse(staff.page, id)
  await staff.page.getByRole('list', { name: '권장 활동' }).getByRole('button', { name: '메일 작성', exact: true }).click()
  await expect(staff.page.getByText('서비스 · dispatch@example.com, second@example.com', { exact: false })).toBeVisible()

  // Add a department, then put the service address back.
  await staff.page.goto('/#/departments')
  const add = staff.page.getByRole('region', { name: '부서 추가' })
  await add.getByLabel('키 (영문 소문자·숫자·_)').fill('supplier')
  await add.getByLabel('이름', { exact: true }).fill('협력사 대응')
  await add.getByLabel('수신 주소 (한 줄에 하나)').fill('partner@example.com')
  await add.getByRole('button', { name: '부서 추가', exact: true }).click()
  await expect(staff.page.getByRole('listitem', { name: '협력사 대응 부서' })).toBeVisible()
  // The test database is shared with other tests of this worker: switch the new department off again.
  const supplier = staff.page.getByRole('listitem', { name: '협력사 대응 부서' })
  await supplier.getByRole('checkbox', { name: '사용' }).uncheck()
  await supplier.getByRole('button', { name: '저장', exact: true }).click()
  await expect(supplier.getByText('저장했습니다.', { exact: true })).toBeVisible()
  await service.getByLabel('수신 주소 (한 줄에 하나)').fill('hodob76@gmail.com')
  await service.getByRole('button', { name: '저장', exact: true }).click()
  await expect(service.getByText('저장했습니다.', { exact: true })).toBeVisible()

  await customer.page.goto('/#/departments')
  await expect(customer.page.getByRole('heading', { name: '부서 메일 설정', exact: true })).toHaveCount(0)
  expect((await customer.page.request.get('/api/v1/service-requests/departments/manage')).status()).toBe(403)
  await customer.context.close()
  await staff.context.close()
})

test('the agent only proposes re-analysis: the card button starts or cancels it', async ({ browser }) => {
  const customer = await newContext(browser, process.env.E2E_CUSTOMER, 'portal')
  const staff = await newContext(browser, process.env.E2E_STAFF, 'cases')
  const id = await createRequest(customer.page, '제안 카드 확인용 증상 설명입니다.')
  await analyse(staff.page, id)
  await analysisDone(staff.page)  // proposals need a finished analysis
  const ask = async (text) => {
    await staff.page.getByLabel('질문 입력', { exact: true }).fill(text)
    await staff.page.getByRole('button', { name: '보내기', exact: true }).click()
  }

  await expect(staff.page.getByRole('region', { name: '추가 정보 저장 제안' })).toHaveCount(0)
  expect(await serverItem(staff.page, id)).not.toHaveProperty('additionalInfo')

  await ask('재분석 제안해 주세요')
  const reCard = staff.page.getByRole('region', { name: '재분석 제안' })
  await expect(reCard.getByText('아직 실행하지 않았습니다', { exact: true })).toBeVisible({ timeout: 15000 })
  expect((await serverItem(staff.page, id)).analysisHistory).toHaveLength(1)  // proposing started nothing
  await reCard.getByRole('button', { name: '재분석 시작', exact: true }).click()
  const log = staff.page.getByRole('log', { name: 'AI 대화 내용' })
  await expect(log.getByText('분석 2회차', { exact: true })).toBeVisible({ timeout: 20000 })
  expect((await serverItem(staff.page, id)).analysisHistory).toHaveLength(2)

  // Cancelling another re-analysis proposal starts no further analysis.
  await ask('재분석 제안해 주세요')
  const second = staff.page.getByRole('region', { name: '재분석 제안' }).last()
  await expect(second.getByRole('button', { name: '취소', exact: true })).toBeVisible({ timeout: 15000 })
  await second.getByRole('button', { name: '취소', exact: true }).click()
  await expect(second.getByText('취소했습니다', { exact: true })).toBeVisible()
  expect((await serverItem(staff.page, id)).analysisHistory).toHaveLength(2)
  expect(JSON.stringify(await serverItem(customer.page, id))).not.toContain('proposals')
  await customer.context.close()
  await staff.context.close()
})

