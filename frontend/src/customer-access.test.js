import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { buildSync } from 'esbuild'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const appRequire = createRequire(import.meta.url)
const compiled = buildSync({ entryPoints: [fileURLToPath(new URL('./CustomerAccess.jsx', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false,
  external: ['react', 'react-dom', 'react-dom/*'], logLevel: 'silent' }).outputFiles[0].text
const loaded = { exports: {} }
new Function('require', 'module', 'exports', compiled)(appRequire, loaded, loaded.exports)
const { Consent } = loaded.exports
const policy = { version: 'synthetic-v1', purpose: '합성 시험', items: '합성 이메일', retention: '시험 종료까지',
  recipients: '외부 전달 없음', contact: '합성 시험 담당자', refusal: '동의를 거부할 수 있습니다. 거부하면 시험 가입을 진행할 수 없습니다.' }

test('actual consent notice includes refusal and restrictions with no preselected agreement', () => {
  const html = renderToStaticMarkup(React.createElement(Consent, { policy, value: false, onChange() {} }))
  assert(html.includes('동의 거부권·거부 시 제한') && html.includes(policy.refusal))
  assert(!html.includes('checked=""'))
  for (const key of ['version', 'purpose', 'items', 'retention', 'recipients', 'contact']) assert(html.includes(policy[key]))
})

test('policy text is displayed as text rather than executable markup', () => {
  const html = renderToStaticMarkup(React.createElement(Consent, { policy: { ...policy, refusal: '<script>synthetic()</script>' }, value: false, onChange() {} }))
  assert(!html.includes('<script>') && html.includes('&lt;script&gt;'))
})
