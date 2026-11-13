import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { createThemeController } from './theme.js'

const KEY = 'claim-ui-theme'

function fixture({ saved = null, dark = false, accessDenied = false, readDenied = false,
  writeDenied = false, mediaUnavailable = false, legacyMedia = false } = {}) {
  const root = { dataset: {} }
  const reads = []
  const writes = []
  const mediaListeners = new Set()
  const storageListeners = new Set()
  const storage = {
    getItem(key) {
      reads.push(key)
      assert.equal(key, KEY)
      if (readDenied) throw new Error('storage read denied')
      return saved
    },
    setItem(key, value) {
      if (writeDenied) throw new Error('storage write denied')
      writes.push([key, value])
      saved = value
    },
  }
  const media = { matches: dark }
  if (legacyMedia) {
    media.addListener = (listener) => mediaListeners.add(listener)
    media.removeListener = (listener) => mediaListeners.delete(listener)
  } else {
    media.addEventListener = (type, listener) => {
      assert.equal(type, 'change')
      mediaListeners.add(listener)
    }
    media.removeEventListener = (type, listener) => {
      assert.equal(type, 'change')
      mediaListeners.delete(listener)
    }
  }
  const browser = {
    document: { documentElement: root },
    matchMedia(query) {
      assert.equal(query, '(prefers-color-scheme: dark)')
      if (mediaUnavailable) throw new Error('matchMedia unavailable')
      return media
    },
    addEventListener(type, listener) {
      assert.equal(type, 'storage')
      storageListeners.add(listener)
    },
    removeEventListener(type, listener) {
      assert.equal(type, 'storage')
      storageListeners.delete(listener)
    },
  }
  Object.defineProperty(browser, 'localStorage', {
    get() {
      if (accessDenied) throw new Error('storage access denied')
      return storage
    },
  })
  return {
    browser, root, storage, reads, writes, mediaListeners, storageListeners,
    setSystemDark(value) {
      media.matches = value
      for (const listener of mediaListeners) listener({ matches: value })
    },
    dispatchStorage(key, newValue, storageArea = storage) {
      for (const listener of storageListeners) listener({ key, newValue, storageArea })
    },
  }
}

test('applies system preference synchronously before any subscriber or rendering', () => {
  const f = fixture({ dark: true })
  const theme = createThemeController(f.browser)
  assert.equal(f.root.dataset.theme, 'dark')
  assert.equal(theme.getPreference(), 'system')
  assert.deepEqual(f.writes, [])
  theme.destroy()
})

test('saved preference wins and explicit changes persist the preference, not resolved color', () => {
  const f = fixture({ saved: 'light', dark: true })
  const { getPreference, setPreference, destroy } = createThemeController(f.browser)
  assert.equal(f.root.dataset.theme, 'light')
  setPreference('dark')
  assert.equal(getPreference(), 'dark')
  assert.equal(f.root.dataset.theme, 'dark')
  setPreference('system')
  assert.equal(getPreference(), 'system')
  assert.equal(f.root.dataset.theme, 'dark')
  assert.deepEqual(f.writes, [[KEY, 'dark'], [KEY, 'system']])
  destroy()
})

test('invalid saved values fall back to system without rewriting browser storage', () => {
  for (const saved of ['', 'DARK', 'unknown', '{"theme":"dark"}']) {
    const f = fixture({ saved, dark: true })
    const theme = createThemeController(f.browser)
    assert.equal(theme.getPreference(), 'system')
    assert.equal(f.root.dataset.theme, 'dark')
    assert.deepEqual(f.writes, [])
    theme.destroy()
  }
})

test('denied storage property, reads, and writes do not prevent in-memory changes', () => {
  for (const options of [{ accessDenied: true }, { readDenied: true }, { writeDenied: true }]) {
    const f = fixture(options)
    const theme = createThemeController(f.browser)
    const snapshots = []
    theme.subscribe(() => snapshots.push([theme.getPreference(), f.root.dataset.theme]))
    assert.doesNotThrow(() => theme.setPreference('dark'))
    assert.equal(theme.getPreference(), 'dark')
    assert.equal(f.root.dataset.theme, 'dark')
    assert.deepEqual(snapshots, [['dark', 'dark']])
    theme.destroy()
  }
})

test('system changes update the applied theme, while explicit preference remains stable', () => {
  const f = fixture()
  const theme = createThemeController(f.browser)
  let notices = 0
  theme.subscribe(() => { notices += 1 })
  f.setSystemDark(true)
  assert.equal(f.root.dataset.theme, 'dark')
  assert.equal(theme.getPreference(), 'system')
  assert.equal(notices, 1)
  theme.setPreference('light')
  f.setSystemDark(false)
  f.setSystemDark(true)
  assert.equal(f.root.dataset.theme, 'light')
  assert.equal(notices, 2)
  theme.setPreference('system')
  assert.equal(f.root.dataset.theme, 'dark')
  theme.destroy()
})

test('unsubscribe and destroy detach all callbacks; methods do not depend on this', () => {
  const f = fixture()
  const { getPreference, setPreference, subscribe, destroy } = createThemeController(f.browser)
  let notices = 0
  const unsubscribe = subscribe(() => { notices += 1 })
  setPreference('dark')
  unsubscribe()
  setPreference('light')
  assert.equal(notices, 1)
  assert.equal(getPreference(), 'light')
  assert.equal(f.mediaListeners.size, 1)
  assert.equal(f.storageListeners.size, 1)
  destroy()
  destroy()
  assert.equal(f.mediaListeners.size, 0)
  assert.equal(f.storageListeners.size, 0)
  subscribe(() => { notices += 1 })
  setPreference('dark')
  f.setSystemDark(true)
  f.dispatchStorage(KEY, 'dark')
  assert.equal(getPreference(), 'light')
  assert.equal(f.root.dataset.theme, 'light')
  assert.equal(notices, 1)
})

test('other-tab storage changes synchronize without writing back or accepting unrelated storage', () => {
  const f = fixture({ dark: true })
  const theme = createThemeController(f.browser)
  f.dispatchStorage('unrelated-setting', 'light')
  assert.equal(theme.getPreference(), 'system')
  f.dispatchStorage(KEY, 'light', {})
  assert.equal(theme.getPreference(), 'system')
  f.dispatchStorage(KEY, 'light')
  assert.equal(theme.getPreference(), 'light')
  assert.equal(f.root.dataset.theme, 'light')
  f.dispatchStorage(KEY, 'invalid')
  assert.equal(theme.getPreference(), 'system')
  assert.equal(f.root.dataset.theme, 'dark')
  theme.setPreference('light')
  f.dispatchStorage(null, null)
  assert.equal(theme.getPreference(), 'system')
  assert.equal(f.root.dataset.theme, 'dark')
  assert.deepEqual(f.writes, [[KEY, 'light']])
  theme.destroy()
})

test('missing browser features fall back safely and legacy media subscriptions are removed', () => {
  const f = fixture({ dark: true, mediaUnavailable: true })
  const theme = createThemeController(f.browser)
  assert.equal(f.root.dataset.theme, 'light')
  theme.setPreference('dark')
  assert.equal(f.root.dataset.theme, 'dark')
  theme.destroy()
  const empty = createThemeController({})
  empty.setPreference('dark')
  assert.equal(empty.getPreference(), 'dark')
  empty.destroy()
  const legacy = fixture({ legacyMedia: true })
  const legacyTheme = createThemeController(legacy.browser)
  legacy.setSystemDark(true)
  assert.equal(legacy.root.dataset.theme, 'dark')
  legacyTheme.destroy()
  assert.equal(legacy.mediaListeners.size, 0)
})

test('invalid explicit preference is rejected without changing state or storage', () => {
  const f = fixture({ saved: 'dark' })
  const theme = createThemeController(f.browser)
  assert.throws(() => theme.setPreference('invalid'), RangeError)
  assert.equal(theme.getPreference(), 'dark')
  assert.equal(f.root.dataset.theme, 'dark')
  assert.deepEqual(f.writes, [])
  theme.destroy()
})

function runHeadBootstrap(f) {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
  const script = scripts.find((match) => !/\bsrc\s*=/i.test(match[1]))
  const appModule = scripts.find((match) => /\bsrc\s*=/i.test(match[1])
    && /\btype\s*=\s*["']module["']/i.test(match[1]))
  assert.ok(script, 'index.html must contain its synchronous theme bootstrap')
  assert.ok(appModule, 'index.html must contain its app module')
  assert.ok(script.index < html.indexOf('</head>'), 'bootstrap must execute in the head')
  assert.ok(script.index < appModule.index, 'bootstrap must precede the app module')
  assert.doesNotMatch(script[1], /\b(?:async|defer)\b|\btype\s*=\s*["']module["']/i)
  const context = { window: f.browser, document: f.browser.document }
  Object.defineProperty(context, 'localStorage', { get: () => f.browser.localStorage })
  runInNewContext(script[2], context, { timeout: 1000 })
}

test('head bootstrap applies saved dark synchronously before the app and uses the controller storage key', () => {
  const f = fixture({ saved: 'dark', dark: false })
  runHeadBootstrap(f)
  // No app/controller has run yet: this tests ordering and state, not device paint timing.
  assert.equal(f.root.dataset.theme, 'dark')
  assert.deepEqual(f.reads, [KEY])
  const theme = createThemeController(f.browser)
  assert.equal(theme.getPreference(), 'dark')
  assert.equal(f.root.dataset.theme, 'dark')
  assert.deepEqual(f.reads, [KEY, KEY])
  assert.deepEqual(f.writes, [])
  theme.destroy()
})

test('head bootstrap survives denied storage access or reads and follows a dark system', () => {
  for (const options of [{ accessDenied: true }, { readDenied: true }]) {
    const f = fixture({ ...options, dark: true })
    assert.doesNotThrow(() => runHeadBootstrap(f))
    assert.equal(f.root.dataset.theme, 'dark')
    const theme = createThemeController(f.browser)
    assert.equal(theme.getPreference(), 'system')
    assert.equal(f.root.dataset.theme, 'dark')
    assert.deepEqual(f.writes, [])
    theme.destroy()
  }
})

test('head bootstrap treats invalid saved values as system and falls back to light without matchMedia', () => {
  for (const saved of ['invalid', 'DARK', '', 'system']) {
    const f = fixture({ saved, dark: true })
    runHeadBootstrap(f)
    assert.equal(f.root.dataset.theme, 'dark')
    const theme = createThemeController(f.browser)
    assert.equal(theme.getPreference(), 'system')
    theme.destroy()
  }
  const unavailable = fixture({ saved: 'invalid', dark: true })
  delete unavailable.browser.matchMedia
  assert.doesNotThrow(() => runHeadBootstrap(unavailable))
  assert.equal(unavailable.root.dataset.theme, 'light')
  const theme = createThemeController(unavailable.browser)
  assert.equal(theme.getPreference(), 'system')
  assert.equal(unavailable.root.dataset.theme, 'light')
  theme.destroy()
})
