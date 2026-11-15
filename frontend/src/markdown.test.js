import test from 'node:test'
import assert from 'node:assert/strict'
import { parseMarkdown } from './domain/markdown.js'

const plain = inlines => inlines.map(part => part.v).join('')

test('bold, code and plain text are separate inline parts, and unmatched markers stay as text', () => {
  const [block] = parseMarkdown('앞 **굵게** 중간 \`코드\` 끝 ** 닫히지 않음')
  assert.deepEqual(block.inlines.map(part => [part.t, part.v]), [
    ['text', '앞 '], ['bold', '굵게'], ['text', ' 중간 '], ['code', '코드'], ['text', ' 끝 ** 닫히지 않음']])
})

test('headings, rules, bullet lists and numbered lists become blocks', () => {
  const blocks = parseMarkdown('# 제목\n\n---\n\n- 첫째\n- 둘째\n  - 들여쓴 항목\n\n1. 하나\n2. 둘')
  assert.deepEqual(blocks.map(b => b.type), ['h', 'hr', 'ul', 'ol'])
  assert.equal(blocks[0].level, 1)
  assert.deepEqual(blocks[2].items.map(plain), ['첫째', '둘째', '들여쓴 항목'])
  assert.deepEqual(blocks[3].items.map(plain), ['하나', '둘'])
})

test('lines of one paragraph keep their line breaks and a blank line starts a new paragraph', () => {
  const blocks = parseMarkdown('첫 줄\n둘째 줄\n\n새 문단')
  assert.deepEqual(blocks.map(b => b.type), ['p', 'p'])
  assert.equal(plain(blocks[0].inlines), '첫 줄\n둘째 줄')
})

test('the answer in the screenshot reads cleanly: no raw ** or --- remain', () => {
  const blocks = parseMarkdown('아래는 **서비스맨 출동 요청 메일 초안**입니다.\n\n---\n\n**제목: [서비스맨 출동 요청] CLM-142**\n\n- **요청 번호:** CLM-142\n- **기종:** VMCT-01\n  - **FSR-08295 (VMCT-05):** DOWN 센서 위치 조절')
  const text = JSON.stringify(blocks)
  assert.ok(!text.includes('**') && blocks.some(b => b.type === 'hr'))
  assert.deepEqual(blocks.at(-1).items.map(plain), ['요청 번호: CLM-142', '기종: VMCT-01', 'FSR-08295 (VMCT-05): DOWN 센서 위치 조절'])
})

test('html and links are never interpreted: they stay literal text', () => {
  const [block] = parseMarkdown('<script>alert(1)</script> [링크](javascript:alert(1)) <b>x</b>')
  assert.deepEqual(block.inlines.map(part => part.t), ['text'])
  assert.equal(plain(block.inlines), '<script>alert(1)</script> [링크](javascript:alert(1)) <b>x</b>')
})

test('empty or non-text input gives no blocks', () => {
  assert.deepEqual(parseMarkdown(''), [])
  assert.deepEqual(parseMarkdown(undefined), [])
  assert.deepEqual(parseMarkdown('\n\n  \n'), [])
})
