import { defineConfig } from '@playwright/test'

// This is NOT part of the default regression suite. It writes clearly marked
// acceptance-test requests into an explicitly approved current environment.
const required = [
  'LIVE_E2E_BASE_URL', 'LIVE_E2E_RUN_TAG',
  'LIVE_E2E_USER_PASSWORD', 'LIVE_E2E_ADMIN_PASSWORD',
  'LIVE_E2E_EXPECTED_USER_ID', 'LIVE_E2E_EXPECTED_ADMIN_ID',
  'LIVE_E2E_USER_EQUIPMENT_ID', 'LIVE_E2E_OTHER_EQUIPMENT_ID',
]
if (process.env.LIVE_E2E_APPROVED_DB !== 'service_poc_test' || required.some(key => !process.env[key])) {
  throw new Error('Current-DB E2E requires explicit approval for service_poc_test, verified identities, fixture IDs and credentials. See docs/tdd.md.')
}
const target = new URL(process.env.LIVE_E2E_BASE_URL)
if (!['localhost', '127.0.0.1', '[::1]'].includes(target.hostname)) {
  throw new Error('Refusing to send current local test credentials to a non-local host')
}

export default defineConfig({
  testDir: './e2e-live',
  workers: 1,
  retries: 0, // Do not silently submit duplicate requests into a shared DB.
  reporter: 'line',
  timeout: 60000,
  use: {
    baseURL: target.origin,
    headless: true,
    trace: 'off',
    screenshot: 'off',
    launchOptions: process.env.PW_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PW_CHROMIUM_EXECUTABLE } : {},
  },
})
