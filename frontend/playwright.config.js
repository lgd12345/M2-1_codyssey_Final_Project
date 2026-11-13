import { defineConfig } from '@playwright/test'

// The Python test harness provisions a disposable DB and supplies real test
// accounts. Never silently fall back to an application server/database.
if (!process.env.E2E_BASE_URL || !process.env.E2E_CUSTOMER || !process.env.E2E_PASSWORD) {
  throw new Error('Run backend/scripts/test_isolated.py tests/test_service_requests_e2e.py with RUN_BROWSER_E2E=1')
}

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  reporter: 'line',
  timeout: 120000,
  expect: { timeout: 8000 },
  use: {
    actionTimeout: 10000, // fail on the missing control instead of hanging until the test timeout
    baseURL: process.env.E2E_BASE_URL,
    headless: true,
    launchOptions: process.env.PW_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PW_CHROMIUM_EXECUTABLE } : {},
  },
})
