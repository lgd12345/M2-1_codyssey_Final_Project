import remarkGfm from 'remark-gfm'
import remarkCjkFriendly from 'remark-cjk-friendly'

// GFM tables, plus CommonMark's emphasis rule fixed for Korean: `**COLUMN(컬럼)**입니다` otherwise stays raw asterisks.
export const remarkPlugins = [remarkGfm, remarkCjkFriendly]
