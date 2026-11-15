import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

// Collection only: fake configuration, no browser, DB, model or SMTP connection.
test('the explicit live suite collects current workflows without duplicate retired scenarios', () => {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const cli = fileURLToPath(new URL('../node_modules/@playwright/test/cli.js', import.meta.url))
  const env = { ...process.env, LIVE_E2E_APPROVED_DB: 'service_poc_test', LIVE_E2E_BASE_URL: 'http://127.0.0.1:4173' }
  for (const key of ['LIVE_E2E_RUN_TAG', 'LIVE_E2E_USER_PASSWORD', 'LIVE_E2E_ADMIN_PASSWORD',
    'LIVE_E2E_EXPECTED_USER_ID', 'LIVE_E2E_EXPECTED_ADMIN_ID', 'LIVE_E2E_USER_EQUIPMENT_ID', 'LIVE_E2E_FOREIGN_REQUEST_ID']) env[key] = 'synthetic-collection-only'
  const output = execFileSync(process.execPath, [cli, 'test', '--config', 'playwright.live.config.js', '--list'],
    { cwd: root, env, encoding: 'utf8', timeout: 30000 })
  assert.match(output, /Total: 4 tests in 1 file/)
  assert.match(output, /direct closure and customer result only/)
  assert.match(output, /retired notes, replies, assignment and work cannot be used/)
})
