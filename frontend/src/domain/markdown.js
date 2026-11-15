// A deliberately small markdown reader for chat answers: headings, rules, lists, **bold** and `code`.
// It returns plain data that React renders as text. HTML, links and images are never interpreted.
function inline(text) {
  const parts = []
  const pattern = /\*\*([^*\n]+?)\*\*|`([^`\n]+?)`/g
  let last = 0
  for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
    if (match.index > last) parts.push({ t: 'text', v: text.slice(last, match.index) })
    parts.push(match[1] !== undefined ? { t: 'bold', v: match[1] } : { t: 'code', v: match[2] })
    last = pattern.lastIndex
  }
  if (last < text.length) parts.push({ t: 'text', v: text.slice(last) })
  return parts
}

export function parseMarkdown(source) {
  const blocks = []
  let paragraph = []
  let list = null
  const flushParagraph = () => { if (paragraph.length) blocks.push({ type: 'p', inlines: inline(paragraph.join('\n')) }); paragraph = [] }
  const flushList = () => { if (list) blocks.push(list); list = null }
  for (const raw of String(source ?? '').split('\n')) {
    const line = raw.replace(/\s+$/, '')
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (!line.trim()) { flushParagraph(); flushList() } else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      flushParagraph(); flushList(); blocks.push({ type: 'hr' })
    } else if (heading) {
      flushParagraph(); flushList(); blocks.push({ type: 'h', level: heading[1].length, inlines: inline(heading[2]) })
    } else if (bullet || numbered) {
      flushParagraph()
      const type = bullet ? 'ul' : 'ol'
      if (list && list.type !== type) flushList()
      list = list ?? { type, items: [] }
      list.items.push(inline((bullet ?? numbered)[1]))
    } else {
      flushList(); paragraph.push(line)
    }
  }
  flushParagraph(); flushList()
  return blocks
}
