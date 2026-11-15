import test from 'node:test'
import assert from 'node:assert/strict'
import { ACTIVITY_LABELS, activitiesFor, firstSentences, mailAiUrl, mailTemplateUrl } from './domain/analysis.js'

const dept = (key, aiSelected, selected = aiSelected) => ({ key, aiSelected, selected })

test('recommended activities are the departments the AI picked, in a fixed order, as mail actions', () => {
  const list = activitiesFor([dept('sales', false), dept('quality', true), dept('service', true), dept('parts', false)])
  assert.deepEqual(list.map(a => a.key), ['service', 'quality'])
  assert.deepEqual(list.map(a => a.label), ['서비스맨 출동 요청 메일', '품질관리부서 보고 메일'])
})

test('no departments, or none picked, means no activities', () => {
  assert.deepEqual(activitiesFor([]), [])
  assert.deepEqual(activitiesFor(undefined), [])
  assert.deepEqual(activitiesFor([dept('service', false)]), [])
  assert.deepEqual(activitiesFor([dept('legal', true)]), [])  // an unknown key is ignored, never shown
})

test('every department has a label and nothing else is shown for an unknown key', () => {
  assert.deepEqual(Object.keys(ACTIVITY_LABELS).sort(), ['parts', 'quality', 'sales', 'service'])
  for (const label of Object.values(ACTIVITY_LABELS)) assert.ok(label.endsWith('메일'))
})

test('long text is cut to its first sentences without breaking the full text', () => {
  const text = '첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.'
  assert.deepEqual(firstSentences(text, 2), { text: '첫 문장입니다. 둘째 문장입니다.', cut: true })
  assert.deepEqual(firstSentences('짧은 한 문장', 2), { text: '짧은 한 문장', cut: false })
  assert.deepEqual(firstSentences('', 2), { text: '', cut: false })
  assert.deepEqual(firstSentences('가나다.'.repeat(100), 1).cut, true)
})

test('mail window addresses carry only a request number and a department key', () => {
  assert.equal(mailTemplateUrl('CLM-005', 'service'), '/service-requests/CLM-005/mail-template?department_key=service')
  assert.equal(mailAiUrl('CLM-005'), '/service-requests/CLM-005/mail-template/ai')
  for (const bad of [['x', 'service'], ['CLM-005', 'a/b'], ['CLM-005', ''], ['CLM-005', 'x'.repeat(40)]]) assert.throws(() => mailTemplateUrl(...bad))
  assert.throws(() => mailAiUrl('nope'))
})
