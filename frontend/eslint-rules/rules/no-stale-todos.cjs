/**
 * giljo-internal/no-stale-todos
 *
 * Flags TODO / FIXME / HACK comments older than 30 days that do NOT
 * reference a project ID (matches XX-NNNN like BE-5042 / FE-5044, or
 * 8-char hex like e02166ed).
 *
 * "Older than 30 days" requires a date hint in the comment. We accept:
 *   - YYYY-MM-DD (e.g. 2026-04-21)
 *   - "(2026-04-21)" or any ISO date embedded anywhere in the comment
 * If a TODO has no date and no project ID, it is flagged regardless
 * (anonymous TODOs are stale by definition).
 */
'use strict'

const STALE_TAG_RE = /\b(TODO|FIXME|HACK)\b/i
const PROJECT_ID_RE = /\b([A-Z]{2,4}-\d{3,5}|[0-9a-f]{8})\b/
const DATE_RE = /(20\d{2})-(\d{2})-(\d{2})/
const MS_PER_DAY = 86400000
const STALE_DAYS = 30

module.exports = {
  meta: {
    type: 'suggestion',
    docs: {
      description:
        'flag TODO/FIXME/HACK older than 30 days without a referenced project ID',
    },
    schema: [
      {
        type: 'object',
        properties: {
          now: { type: 'string' }, // ISO date, override for tests
        },
        additionalProperties: false,
      },
    ],
    messages: {
      stale:
        'Stale {{tag}} (date {{date}}, >{{days}} days old) without a project ID. File a project (XX-NNNN) and reference it, or resolve it.',
      anonymous:
        'Anonymous {{tag}} with no date and no project ID. Add a project ID (XX-NNNN) or remove the comment.',
    },
  },
  create(context) {
    const opts = context.options[0] || {}
    const now = opts.now ? new Date(opts.now) : new Date()
    const sourceCode = context.sourceCode
    return {
      Program() {
        for (const c of sourceCode.getAllComments()) {
          const txt = c.value
          const tagMatch = txt.match(STALE_TAG_RE)
          if (!tagMatch) continue
          const tag = tagMatch[1].toUpperCase()
          const hasProjectId = PROJECT_ID_RE.test(txt)
          const dateMatch = txt.match(DATE_RE)
          if (!dateMatch && !hasProjectId) {
            context.report({ node: c, messageId: 'anonymous', data: { tag } })
            continue
          }
          if (dateMatch) {
            const d = new Date(dateMatch[0])
            const ageDays = (now - d) / MS_PER_DAY
            if (ageDays > STALE_DAYS && !hasProjectId) {
              context.report({
                node: c,
                messageId: 'stale',
                data: { tag, date: dateMatch[0], days: String(STALE_DAYS) },
              })
            }
          }
        }
      },
    }
  },
}
