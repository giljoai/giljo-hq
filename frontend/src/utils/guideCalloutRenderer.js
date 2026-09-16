
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- consumed by tests/
export const CALLOUT_LABELS = Object.freeze({
  CE: 'Community Edition only',
  SAAS: 'Hosted (SaaS) only',
})

export function installGuideCalloutRenderer(markedInstance) {
  markedInstance.use({
    renderer: {
      heading({ text, depth }) {
        const safeText = _escapeHtml(text)
        const anchor = _slugify(text)
        return `<h${depth} id="${anchor}">${safeText}</h${depth}>\n`
      },

      blockquote({ tokens }) {
        const firstToken = tokens.find((t) => t.type !== 'space')

        if (!firstToken || firstToken.type !== 'paragraph') {
          const body = markedInstance.parser(tokens, { renderer: this })
          return `<blockquote>${body}</blockquote>\n`
        }

        const markerMatch = firstToken.text.match(/^\[!(CE|SAAS)\](\n|$)/i)
        if (!markerMatch) {
          const body = markedInstance.parser(tokens, { renderer: this })
          return `<blockquote>${body}</blockquote>\n`
        }

        const kind = markerMatch[1].toUpperCase()
        const label = CALLOUT_LABELS[kind]

        const restText = firstToken.text.slice(markerMatch[0].length).trimStart()
        let bodyTokens

        if (restText) {
          const stripped = {
            ...firstToken,
            text: restText,
            raw: restText,
            tokens: [{ type: 'text', raw: restText, text: restText }],
          }
          bodyTokens = [stripped, ...tokens.slice(tokens.indexOf(firstToken) + 1)]
        } else {
          const firstIdx = tokens.indexOf(firstToken)
          bodyTokens = tokens.slice(firstIdx + 1).filter((t) => t.type !== 'space' || tokens.indexOf(t) > firstIdx + 1)
        }

        const innerBody = markedInstance.parser(bodyTokens, { renderer: this })
        const cls = kind.toLowerCase()
        return `<blockquote class="guide-callout guide-callout--${cls}"><span class="guide-callout__label">${label}</span>${innerBody}</blockquote>\n`
      },
    },
  })
}


const _HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const _HTML_ESCAPE_RE = /[&<>"']/g

function _escapeHtml(value) {
  if (value === null || value === undefined) return ''
  return String(value).replace(_HTML_ESCAPE_RE, (ch) => _HTML_ESCAPES[ch])
}

function _slugify(text) {
  return String(text ?? '')
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}
