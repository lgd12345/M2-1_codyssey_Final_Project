import test from 'node:test'
import assert from 'node:assert/strict'
import * as documents from './documents.js'
import { documentRow, summaryLine } from './documents.js'

test('there is no document type: it was a guess from file names, so nothing is labelled by it', () => {
  assert.equal(documents.kindLabel, undefined)
  const row = documentRow({ id: 'x', title: 't', document_kind: 'parts_list', machines: ['F400'], manufacturer: 'FANUC',
    page_count: 1, searchable_pages: 1, embedded_pages: 1 })
  assert.equal('kind' in row, false)
})

test('summary line states the document count, searchable pages and whether vector search is on', () => {
  const overview = { total: 11, page_count: 1039, searchable_pages: 970, embedded_pages: 0, vector_search: 'inactive' }
  assert.equal(summaryLine(overview), '문서 11개 · 검색 대상 970/1,039쪽 · 벡터 색인 0쪽 · 벡터 검색 꺼짐')
  assert.equal(summaryLine({ ...overview, embedded_pages: 838, vector_search: 'active' }),
    '문서 11개 · 검색 대상 970/1,039쪽 · 벡터 색인 838쪽 · 벡터 검색 켜짐')
  assert.equal(summaryLine(null), '문서 정보를 불러오는 중…')
})

test('a row shows machines, page counts and vector progress', () => {
  const row = documentRow({ id: 'abc', title: 'F400VM PARTS LIST', machines: ['F400', 'F400_500_650VM'],
    manufacturer: 'FANUC', page_count: 104, searchable_pages: 90, embedded_pages: 45 })
  assert.deepEqual(row, { key: 'abc', title: 'F400VM PARTS LIST', machines: 'F400, F400_500_650VM',
    manufacturer: 'FANUC', pages: '104쪽', searchable: '90쪽', vector: '45/90' })
  assert.equal(documentRow({ id: 'x', title: 't', machines: [], manufacturer: null,
    page_count: 1, searchable_pages: 0, embedded_pages: 0 }).machines, '-')
})
