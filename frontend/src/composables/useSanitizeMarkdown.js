import DOMPurify from 'dompurify'
import { marked } from 'marked'

const HARDENED_CONFIG = Object.freeze({
  ALLOWED_TAGS: [
    'a', 'b', 'i', 'em', 'strong', 'mark',
    'p', 'br', 'hr', 'div', 'span',
    'code', 'pre', 'blockquote',
    'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'img',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
  ],
  ALLOWED_ATTR: ['href', 'target', 'rel', 'src', 'alt', 'id', 'class'],
  ALLOW_DATA_ATTR: false,
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.:-]|$))/i,
  FORBID_ATTR: ['onerror', 'onclick', 'onload', 'onmouseover', 'onfocus', 'onblur'],
})

const GUIDE_CALLOUT_CLASSES = new Set([
  'guide-callout',
  'guide-callout--ce',
  'guide-callout--saas',
])

let _calloutHookInstalled = false
function ensureCalloutHook() {
  if (_calloutHookInstalled) return
  _calloutHookInstalled = true
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName !== 'BLOCKQUOTE') return
    const cls = node.getAttribute('class')
    if (!cls) return
    const kept = cls
      .split(/\s+/)
      .filter((c) => GUIDE_CALLOUT_CLASSES.has(c))
      .join(' ')
    if (kept) {
      node.setAttribute('class', kept)
    } else {
      node.removeAttribute('class')
    }
  })
}

function buildConfig(overrides) {
  if (!overrides) return HARDENED_CONFIG
  return { ...HARDENED_CONFIG, ...overrides }
}

export function sanitizeHtml(html, overrides) {
  if (!html) return ''
  ensureCalloutHook()
  return DOMPurify.sanitize(html, buildConfig(overrides))
}

export function useSanitizeMarkdown() {
  function sanitizeMarkdown(content, overrides) {
    if (!content) return ''
    ensureCalloutHook()
    const html = marked(content)
    return DOMPurify.sanitize(html, buildConfig(overrides))
  }

  return { sanitizeMarkdown }
}
