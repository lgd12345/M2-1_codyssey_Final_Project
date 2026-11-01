// Display helpers for the registered-document panel (pure, so they are unit-tested).
// Documents carry no "type": it was guessed from file names, so nothing here is labelled by it.

const n = (value) => Number(value).toLocaleString('ko-KR')

export function summaryLine(overview) {
  if (!overview) return '문서 정보를 불러오는 중…'
  return [`문서 ${n(overview.total)}개`,
    `검색 대상 ${n(overview.searchable_pages)}/${n(overview.page_count)}쪽`,
    `벡터 색인 ${n(overview.embedded_pages)}쪽`,
    `벡터 검색 ${overview.vector_search === 'active' ? '켜짐' : '꺼짐'}`].join(' · ')
}

export function documentRow(doc) {
  return {
    key: doc.id, title: doc.title,
    machines: doc.machines?.length ? doc.machines.join(', ') : '-',
    manufacturer: doc.manufacturer, pages: `${doc.page_count}쪽`,
    searchable: `${doc.searchable_pages}쪽`, vector: `${doc.embedded_pages}/${doc.searchable_pages}`,
  }
}
