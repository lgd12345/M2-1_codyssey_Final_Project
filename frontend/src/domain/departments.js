// Pure helpers of the department settings screen. The server validates everything again.
const ADDRESS = /^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/
const KEY = /^[a-z][a-z0-9_]{1,30}$/

export const isValidKey = key => KEY.test(key ?? '')

export function parseRecipients(text) {
  const list = [], invalid = []
  for (const part of String(text ?? '').split(/[\n,]/)) {
    const value = part.trim()
    if (!value) continue
    const address = value.toLowerCase()
    if (!ADDRESS.test(address)) invalid.push(value)
    else if (!list.includes(address)) list.push(address)
  }
  return { list, invalid }
}

export function departmentChange(saved, draft) {
  const change = {}
  if (draft.name.trim() !== saved.name) change.name = draft.name.trim()
  if (draft.description.trim() !== saved.description) change.description = draft.description.trim()
  const { list } = parseRecipients(draft.recipientsText)
  if (JSON.stringify(list) !== JSON.stringify(saved.recipients)) change.recipients = list
  if (draft.active !== saved.active) change.active = draft.active
  return change
}
