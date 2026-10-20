/**
 * giljo-internal/no-vite-ignore-saas-import
 *
 * Flags `import(/* @vite-ignore *\/ pathString)`. ADR-002 bans @vite-ignore
 * dynamic imports because Vite can't tree-shake them, the chunk graph is
 * broken on first paint, and CE/SaaS code splitting becomes guesswork.
 * Use `import.meta.glob` with eager: false instead.
 */
'use strict'

module.exports = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'disallow dynamic `import(/* @vite-ignore */ ...)`; use import.meta.glob (ADR-002)',
    },
    schema: [],
    messages: {
      viteIgnore:
        '`/* @vite-ignore */` dynamic imports are banned (ADR-002). Use import.meta.glob({ eager: false }) and pick the matching loader.',
    },
  },
  create(context) {
    const src = context.sourceCode
    return {
      ImportExpression(node) {
        // Check leading or inner comments for "@vite-ignore"
        const all = src.getAllComments()
        const start = node.range[0]
        const end = node.range[1]
        for (const c of all) {
          if (c.range[0] >= start && c.range[1] <= end && c.value.includes('@vite-ignore')) {
            context.report({ node, messageId: 'viteIgnore' })
            return
          }
        }
      },
    }
  },
}
