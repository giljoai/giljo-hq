/**
 * giljo-internal/no-manual-api-url-composition
 *
 * Flags template literals of shape `${proto}://${host}:${port}` that manually
 * compose a base URL. ADR-001 requires using getApiBaseUrl()/getWsBaseUrl()
 * from @/composables/useApiUrl so the frontend talks to the host the browser
 * is on (reverse-proxy friendly) instead of an internal config-leaked address.
 *
 * Per-file allowlist: place the comment
 *   // eslint-allow giljo-internal/no-manual-api-url-composition
 * anywhere in the file to suppress this rule for that file. Use only for
 * sanctioned exceptions: useMcpConfig.js (MCP-server URLs for AI-tool
 * config files) and views that
 * display a target URL to the user (DashboardView.vue, Login.vue) rather
 * than using it as an HTTP client base.
 */
'use strict'

const ALLOWLIST_MARKER = 'eslint-allow giljo-internal/no-manual-api-url-composition'

function isFileAllowlisted(context) {
  const src = context.sourceCode || (context.getSourceCode && context.getSourceCode())
  if (!src || !src.text) return false
  return src.text.includes(ALLOWLIST_MARKER)
}

function templateHasProtoHostPort(node) {
  // `${proto}://${host}:${port}` has quasis joined together containing
  // `://` and `:` separators between three expression slots.
  if (!node.quasis || node.quasis.length < 3) return false
  if (!node.expressions || node.expressions.length < 3) return false
  const joined = node.quasis.map((q) => q.value.raw).join('|')
  // Must contain "://" (between proto and host) AND a ":" (between host and port).
  return /:\/\//.test(joined) && /(^|\|):($|\|)/.test(joined)
}

module.exports = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'disallow manual `${protocol}://${host}:${port}` URL composition; use getApiBaseUrl()/getWsBaseUrl() from @/composables/useApiUrl (ADR-001)',
    },
    schema: [],
    messages: {
      manual:
        'Manual `${protocol}://${host}:${port}` composition leaks internal addresses. Use getApiBaseUrl() or getWsBaseUrl() from @/composables/useApiUrl (ADR-001).',
    },
  },
  create(context) {
    if (isFileAllowlisted(context)) return {}
    return {
      TemplateLiteral(node) {
        if (templateHasProtoHostPort(node)) {
          context.report({ node, messageId: 'manual' })
        }
      },
    }
  },
}
