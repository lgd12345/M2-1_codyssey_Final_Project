import test from 'node:test'
import assert from 'node:assert/strict'
import { SAMPLES } from './samples.js'

test('every sample has a label and a reasonably short question, and none repeats', () => {
  assert.ok(SAMPLES.length >= 8 && SAMPLES.length <= 12)
  for (const sample of SAMPLES) {
    assert.ok(sample.label.trim() && sample.question.trim())
    assert.ok(sample.question.length <= 120, `too long: ${sample.question}`)
  }
  assert.equal(new Set(SAMPLES.map((s) => s.question)).size, SAMPLES.length)
})

test('labels describe how the question is answered, never a type of document', () => {
  // Documents have no type any more (it was a guess from file names), so no chip may be labelled by one.
  const documentWords = /자료조사|트러블슈팅|부품 ?목록|정비 ?매뉴얼|안전장치|회로도|참고 ?자료|매뉴얼/
  for (const sample of SAMPLES) assert.doesNotMatch(sample.label, documentWords, sample.label)
})

test('samples cover each way the agent finds information', () => {
  const labels = new Set(SAMPLES.map((s) => s.label))
  for (const kind of ['알람 번호', '증상', 'PMC 주소', '품번', '도면번호', '절차', '안전', '내용 질문']) {
    assert.ok(labels.has(kind), `missing a "${kind}" sample`)
  }
})

test('samples also cover the two outcomes that are not a cited answer', () => {
  const labels = SAMPLES.map((s) => s.label)
  assert.ok(labels.includes('인사'), 'a greeting shows the "no manual evidence" reply')
  assert.ok(labels.includes('문서에 없는 내용'), 'a question the manuals cannot answer shows "not enough evidence"')
})

test('identifier samples use values that exist in the registered manuals', () => {
  const text = SAMPLES.map((s) => s.question).join('\n')
  for (const real of ['2026', 'X0004.7', '2064-01-101-01', '2064-05-003-03']) assert.ok(text.includes(real), real)
})

test('the question the manuals cannot answer is a labelled control, not presented as a normal sample', () => {
  const control = SAMPLES.find((s) => s.label === '문서에 없는 내용')
  assert.match(control.question, /서보모터 과열/)   // "과열" appears on one unrelated page; there is no such procedure
  assert.equal(SAMPLES.filter((s) => /서보모터 과열/.test(s.question)).length, 1)
})
