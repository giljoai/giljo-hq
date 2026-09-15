const HTML_ESCAPES = Object.freeze({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
})

const HTML_ESCAPE_RE = /[&<>"']/g

export function escapeHtml(value) {
  if (value === null || value === undefined) return ''
  return String(value).replace(HTML_ESCAPE_RE, (ch) => HTML_ESCAPES[ch])
}

export function slugify(text) {
  return String(text ?? '')
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}
