import test from 'node:test'
import assert from 'node:assert/strict'
import config from '../vite.config.js'

for (const mode of ['server', 'preview']) {
  test(`${mode} API proxy preserves the browser Host for same-origin checks`, () => {
    const proxy = config[mode]?.proxy?.['/api']
    assert.equal(typeof proxy, 'object')
    assert.equal(proxy.target, process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000')
    assert.equal(proxy.changeOrigin, false)
  })
}
