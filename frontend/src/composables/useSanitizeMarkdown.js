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

const UNTRUSTED_CONFIG = Object.freeze({
  ...HARDENED_CONFIG,
  ALLOWED_ATTR: HARDENED_CONFIG.ALLOWED_ATTR.filter((name) => name !== 'id' && name !== 'class'),
})

const INLINE_IMAGE = /^data:image\//i

function linkifyRemoteImages(html) {
  const template = document.createElement('template')
  template.innerHTML = html
  for (const img of template.content.querySelectorAll('img')) {
    const src = (img.getAttribute('src') || '').trim()
    if (INLINE_IMAGE.test(src)) continue
    if (!src || /^data:/i.test(src)) {
      img.remove()
      continue
    }
    if (img.closest('a')) {
      img.replaceWith(document.createTextNode(src))
      continue
    }
    const link = document.createElement('a')
    link.setAttribute('href', src)
    link.setAttribute('target', '_blank')
    link.setAttribute('rel', 'noopener noreferrer nofollow')
    link.textContent = src
    img.replaceWith(link)
  }
  return template.innerHTML
}

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

function buildConfig(overrides, base = HARDENED_CONFIG) {
  if (!overrides) return base
  return { ...base, ...overrides }
}

export function sanitizeHtml(html, overrides) {
  if (!html) return ''
  ensureCalloutHook()
  return DOMPurify.sanitize(html, buildConfig(overrides))
}

export function useSanitizeMarkdown({ trusted = false } = {}) {
  function sanitizeMarkdown(content, overrides) {
    if (!content) return ''
    ensureCalloutHook()
    const html = marked(content)
    if (trusted) return DOMPurify.sanitize(html, buildConfig(overrides))
    return linkifyRemoteImages(DOMPurify.sanitize(html, buildConfig(overrides, UNTRUSTED_CONFIG)))
  }

  return { sanitizeMarkdown }
}
