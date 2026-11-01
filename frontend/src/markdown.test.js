import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ReactMarkdown from 'react-markdown'
import { remarkPlugins } from './markdown.js'

const render = (markdown) => renderToStaticMarkup(createElement(ReactMarkdown, { remarkPlugins }, markdown))

test('bold followed directly by Korean text is rendered, not shown as raw asterisks', () => {
  const html = render('명칭은 **COLUMN(컬럼)**입니다.')
  assert.match(html, /<strong>COLUMN\(컬럼\)<\/strong>입니다/)
  assert.doesNotMatch(html, /\*\*/)
})

test('bold around brackets and page numbers followed by a particle', () => {
  const html = render('원본 PDF **『F400VM(2064)』 9페이지(PL-5)**의 부품표')
  assert.match(html, /<strong>『F400VM\(2064\)』 9페이지\(PL-5\)<\/strong>의/)
})

test('tables from GFM still render', () => {
  assert.match(render('| 번호 | 이름 |\n| --- | --- |\n| 1 | COLUMN |'), /<table>/)
})

test('raw HTML in an answer is not rendered as markup', () => {
  const html = render('<img src="https://evil.example/x.png"><script>alert(1)</script>')
  assert.doesNotMatch(html, /<img/)
  assert.doesNotMatch(html, /<script/)
})
