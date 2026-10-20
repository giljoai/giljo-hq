/**
 * giljo-internal/no-scattered-mode-checks
 *
 * Flags scattered `mode === 'ce' | 'saas' | 'demo'` and
 * `GILJO_MODE === '...'` comparisons outside a centralized edition module
 * (composables/useGiljoMode.*, saas/composables/useSaasMode.*, or
 * services/configService — the mode source of truth).
 *
 * Per CLAUDE.md edition gating patterns, capability checks should be funneled
 * through one module so adding a new edition is a one-file change. Components
 * delegate to useGiljoMode() (isCeMode/isSaasMode/isNonCeMode or the stateless
 * isCeModeValue/isSaasModeValue/isNonCeModeValue helpers) instead of comparing
 * a raw mode string inline.
 *
 * Detection covers script BinaryExpressions AND Vue `<template>` expressions
 * (v-if="mode === 'ce'"), and unwraps `.value` ref access (giljoMode.value)
 * and optional chaining (status?.mode) so the "0 warnings" reading is trustworthy.
 */
'use strict'

const MODE_VALUES = new Set(['ce', 'saas', 'demo'])

function isAllowlistedFilename(filename) {
  if (!filename) return false
  const lower = filename.replace(/\\/g, '/').toLowerCase()
  // The centralized edition modules are allowed to switch on mode directly.
  return (
    lower.includes('/saas/composables/usesaasmode') ||
    lower.includes('/composables/usegiljomode') ||
    lower.includes('/services/configservice') // mode source of truth
  )
}

function getStringLit(node) {
  if (!node) return null
  if (node.type === 'Literal' && typeof node.value === 'string') return node.value
  return null
}

// Unwrap `ChainExpression` (optional chaining, e.g. `status?.mode`) and
// `.value` ref access (e.g. `giljoMode.value`) so the underlying mode
// identifier/member is inspected.
function unwrapModeExpr(node) {
  if (!node) return node
  if (node.type === 'ChainExpression') return unwrapModeExpr(node.expression)
  if (
    node.type === 'MemberExpression' &&
    !node.computed &&
    node.property &&
    node.property.type === 'Identifier' &&
    node.property.name === 'value'
  ) {
    return unwrapModeExpr(node.object)
  }
  return node
}

function modeRefNode(node) {
  const n = unwrapModeExpr(node)
  if (!n) return null
  if (n.type === 'Identifier') {
    return /mode$/i.test(n.name) || n.name === 'GILJO_MODE' ? n : null
  }
  if (n.type === 'MemberExpression' && n.property && n.property.name) {
    return /mode$/i.test(n.property.name) || n.property.name === 'GILJO_MODE' ? n : null
  }
  return null
}

module.exports = {
  meta: {
    type: 'suggestion',
    docs: {
      description:
        'disallow scattered `mode === "ce" | "saas" | "demo"` checks outside a centralized edition module',
    },
    schema: [],
    messages: {
      scattered:
        'Scattered mode check (`{{name}} === "{{value}}"`). Funnel through useGiljoMode / useSaasMode so adding a new edition is a one-file change.',
    },
  },
  create(context) {
    const filename = context.filename
    if (isAllowlistedFilename(filename)) return {}

    function checkBinary(node) {
      if (
        node.operator !== '===' &&
        node.operator !== '==' &&
        node.operator !== '!==' &&
        node.operator !== '!='
      )
        return
      const lit = getStringLit(node.right) || getStringLit(node.left)
      if (!lit || !MODE_VALUES.has(lit)) return
      const ref = modeRefNode(node.left) || modeRefNode(node.right)
      if (!ref) return
      const name = ref.type === 'Identifier' ? ref.name : ref.property.name
      context.report({ node, messageId: 'scattered', data: { name, value: lit } })
    }

    const scriptVisitor = { BinaryExpression: checkBinary }

    // For .vue files, also walk the <template> body so v-if / v-show / bound
    // prop expressions are inspected (they live in a separate AST that a plain
    // script visitor never reaches).
    const sourceCode = context.sourceCode
    const services =
      (sourceCode && sourceCode.parserServices) || context.parserServices || {}
    if (typeof services.defineTemplateBodyVisitor === 'function') {
      return services.defineTemplateBodyVisitor(
        { BinaryExpression: checkBinary },
        scriptVisitor,
      )
    }
    return scriptVisitor
  },
}
