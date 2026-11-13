const STORAGE_KEY = 'claim-ui-theme'
const PREFERENCES = ['light', 'dark', 'system']

const isPreference = (value) => PREFERENCES.includes(value)
const storedPreference = (value) => isPreference(value) ? value : 'system'

export function createThemeController(browser) {
  let storage
  let media
  let preference = 'system'
  let destroyed = false
  const listeners = new Set()
  const root = browser?.document?.documentElement

  // Storage may be unavailable even when the browser exposes the property.
  try { storage = browser?.localStorage } catch {}
  try { preference = storedPreference(storage?.getItem(STORAGE_KEY)) } catch {}
  try { media = browser?.matchMedia?.('(prefers-color-scheme: dark)') } catch {}

  function apply() {
    if (root?.dataset) {
      root.dataset.theme = preference === 'system'
        ? (media?.matches ? 'dark' : 'light')
        : preference
    }
  }

  function notify() {
    for (const listener of listeners) listener()
  }

  function changePreference(next, persist) {
    if (destroyed) return
    const changed = preference !== next
    preference = next
    apply()
    if (persist) {
      try { storage?.setItem(STORAGE_KEY, next) } catch {}
    }
    if (changed) notify()
  }

  function onSystemChange() {
    if (!destroyed && preference === 'system') {
      apply()
      notify()
    }
  }

  function onStorage(event) {
    if (event.key !== STORAGE_KEY && event.key !== null) return
    if (storage && event.storageArea && event.storageArea !== storage) return
    changePreference(storedPreference(event.newValue), false)
  }

  // Runs synchronously so callers can construct the controller before React renders.
  apply()
  browser?.addEventListener?.('storage', onStorage)
  if (media?.addEventListener) media.addEventListener('change', onSystemChange)
  else media?.addListener?.(onSystemChange)

  return {
    getPreference: () => preference,
    setPreference: (next) => {
      if (!isPreference(next)) throw new RangeError('Unknown theme preference')
      changePreference(next, true)
    },
    subscribe: (listener) => {
      if (destroyed) return () => {}
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    destroy: () => {
      if (destroyed) return
      destroyed = true
      browser?.removeEventListener?.('storage', onStorage)
      if (media?.removeEventListener) media.removeEventListener('change', onSystemChange)
      else media?.removeListener?.(onSystemChange)
      listeners.clear()
    },
  }
}
