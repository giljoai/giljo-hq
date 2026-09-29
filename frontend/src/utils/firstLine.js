
export function firstLine(text) {
  if (!text) return ''
  const line = String(text)
    .split(/\r?\n/)
    .map((l) => l.trim())
    .find((l) => l.length > 0)
  return line || ''
}
