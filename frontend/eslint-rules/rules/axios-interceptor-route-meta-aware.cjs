/**
 * giljo-internal/axios-interceptor-route-meta-aware
 *
 * Flags axios response interceptors that redirect to /login (router.push /
 * location.href / location.replace) without first checking
 * `meta.requiresAuth === false` on the originating request config.
 *
 * Anti-pattern D from the IMP-0013 audit: guard-like probes that legitimately
 * 401 should be able to opt out of the auto-redirect via
 *   axios(url, { meta: { requiresAuth: false } })
 */
'use strict'

function isInterceptorsResponseUse(callee) {
  // axios.interceptors.response.use OR <client>.interceptors.response.use
  if (!callee || callee.type !== 'MemberExpression') return false
  if (!callee.property || callee.property.name !== 'use') return false
  const inner = callee.object
  if (!inner || inner.type !== 'MemberExpression') return false
  if (!inner.property || inner.property.name !== 'response') return false
  const outer = inner.object
  if (!outer || outer.type !== 'MemberExpression') return false
  return outer.property && outer.property.name === 'interceptors'
}

function bodyAsText(node, sourceCode) {
  if (!node) return ''
  return sourceCode.getText(node)
}

function looksLikeLoginRedirect(text) {
  if (!text) return false
  // router.push('/login') | router.replace('/login') | location.href = '/login'
  // | window.location.href = ... | location.assign('/login')
  return (
    /router\s*\.\s*(?:push|replace)\s*\(\s*['"`]\/login/.test(text) ||
    /location\s*\.\s*(?:href|assign|replace)\s*[=(]\s*['"`]\/login/.test(text) ||
    /window\s*\.\s*location\s*\.\s*href\s*=\s*['"`]\/login/.test(text)
  )
}

function hasRequiresAuthFalseGuard(text) {
  if (!text) return false
  return /meta\??\s*\.\s*requiresAuth\s*===\s*false/.test(text) ||
    /requiresAuth\s*:\s*false/.test(text)
}

module.exports = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'axios response interceptors that redirect to /login must check meta.requiresAuth === false first',
    },
    schema: [],
    messages: {
      missingGuard:
        'axios response interceptor redirects to /login without checking `originalRequest.meta?.requiresAuth === false`. Guard-like probes need an opt-out (IMP-0013 anti-pattern D).',
    },
  },
  create(context) {
    const sourceCode = context.sourceCode
    return {
      CallExpression(node) {
        if (!isInterceptorsResponseUse(node.callee)) return
        // Inspect each callback arg
        for (const cb of node.arguments) {
          if (
            cb &&
            (cb.type === 'FunctionExpression' || cb.type === 'ArrowFunctionExpression')
          ) {
            const text = bodyAsText(cb.body, sourceCode)
            if (looksLikeLoginRedirect(text) && !hasRequiresAuthFalseGuard(text)) {
              context.report({ node: cb, messageId: 'missingGuard' })
            }
          }
        }
      },
    }
  },
}
