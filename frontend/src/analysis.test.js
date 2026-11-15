import test from 'node:test'
import assert from 'node:assert/strict'
import { ACTIVITY_LABELS, activitiesFor, activityQuestion, firstSentences, CHAT_ASK_EVENT } from './domain/analysis.js'

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

test('every department has a label and the question asks for a DRAFT, never for sending', () => {
  for (const [key, label] of Object.entries(ACTIVITY_LABELS)) {
    const text = activityQuestion({ key, label })
    assert.ok(text.includes(label) && text.includes('메일 초안'), text)
    assert.ok(!text.includes('보내줘'))
    assert.ok(text.length < 200)
  }
  assert.deepEqual(Object.keys(ACTIVITY_LABELS).sort(), ['parts', 'quality', 'sales', 'service'])
})

test('long text is cut to its first sentences without breaking the full text', () => {
  const text = '첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.'
  assert.deepEqual(firstSentences(text, 2), { text: '첫 문장입니다. 둘째 문장입니다.', cut: true })
  assert.deepEqual(firstSentences('짧은 한 문장', 2), { text: '짧은 한 문장', cut: false })
  assert.deepEqual(firstSentences('', 2), { text: '', cut: false })
  assert.deepEqual(firstSentences('가나다.'.repeat(100), 1).cut, true)
})

test('the chat is asked through one named event', () => {
  assert.equal(CHAT_ASK_EVENT, 'morrono-chat-ask')
})
