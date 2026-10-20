/**
 * giljo-internal/no-vuetify-dialog-chrome
 *
 * Flags Vuetify dialog-chrome anti-patterns (<v-card-title>, <v-card-actions>,
 * and class="text-medium-emphasis") used INSIDE a <v-dialog> block.
 *
 * The design system (main.scss + .dlg-header/.dlg-footer) provides the
 * canonical replacement:
 *   <v-card-title>  →  <div class="dlg-header"> ... </div>
 *   <v-card-actions>→  <div class="dlg-footer"> ... </div>
 *   text-medium-emphasis → --text-muted / --text-secondary CSS variables
 *
 * Detection is text-based (same pattern as sibling rules) so it works in both
 * the Vue template context and the plain RuleTester used by all-rules.spec.js.
 * The rule only fires when the matched element is inside a <v-dialog>…</v-dialog>
 * block, determined by scanning the surrounding source text.
 *
 * Per-file allowlist: place the comment
 *   // eslint-allow giljo-internal/no-vuetify-dialog-chrome
 * anywhere in the file to suppress all reports for that file.
 */
'use strict'

const ALLOWLIST_MARKER = 'eslint-allow giljo-internal/no-vuetify-dialog-chrome'

// Patterns that are forbidden inside dialog context
const VIOLATIONS = [
  {
    re: /<v-card-title[\s>]/g,
    messageId: 'cardTitle',
  },
  {
    re: /<v-card-actions[\s>]/g,
    messageId: 'cardActions',
  },
  {
    re: /class="[^"]*\btext-medium-emphasis\b[^"]*"/g,
    messageId: 'textMediumEmphasis',
  },
]

function isFileAllowlisted(context) {
  const src = context.sourceCode
  if (!src || !src.text) return false
  return src.text.includes(ALLOWLIST_MARKER)
}

/**
 * Build an array of [start, end] index ranges for every <v-dialog>...</v-dialog>
 * block found in the source text (handles self-closing and nested tags
 * approximately — sufficient for the Vue SFC patterns in this codebase).
 */
function findDialogRanges(src) {
  const ranges = []
  const OPEN_RE = /<v-dialog[\s>]/g
  let m
  while ((m = OPEN_RE.exec(src)) !== null) {
    const openStart = m.index
    // Walk forward tracking nesting depth (handle nested v-dialog if any)
    let depth = 1
    let pos = m.index + m[0].length
    // Advance past the opening tag's attribute list to its closing >
    while (pos < src.length && depth > 0) {
      const nextOpen = src.indexOf('<v-dialog', pos)
      const nextClose = src.indexOf('</v-dialog>', pos)
      if (nextClose === -1) break // malformed — skip
      if (nextOpen !== -1 && nextOpen < nextClose) {
        depth++
        pos = nextOpen + 9 // length of '<v-dialog'
      } else {
        depth--
        if (depth === 0) {
          ranges.push([openStart, nextClose + 11]) // 11 = length of '</v-dialog>'
          pos = nextClose + 11
        } else {
          pos = nextClose + 11
        }
      }
    }
  }
  return ranges
}

/**
 * Return true when the match at `index` falls inside any dialog range.
 */
function isInsideDialog(index, ranges) {
  for (const [start, end] of ranges) {
    if (index >= start && index < end) return true
  }
  return false
}

/**
 * Convert a character offset in `src` to a 1-based { line, column } location.
 * (column is 0-based, matching ESLint convention.)
 */
function offsetToLoc(src, offset) {
  const before = src.slice(0, offset)
  const lines = before.split('\n')
  return { line: lines.length, column: lines[lines.length - 1].length }
}

module.exports = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'disallow <v-card-title>, <v-card-actions>, and text-medium-emphasis as dialog chrome inside <v-dialog> — use .dlg-header / .dlg-footer from main.scss instead',
    },
    schema: [],
    messages: {
      cardTitle:
        '<v-card-title> used as dialog chrome. Replace with <div class="dlg-header"> from main.scss (design-system §20).',
      cardActions:
        '<v-card-actions> used as dialog footer. Replace with <div class="dlg-footer"> from main.scss (design-system §20).',
      textMediumEmphasis:
        'text-medium-emphasis inside a dialog — use var(--text-muted) or var(--text-secondary) instead.',
    },
  },
  create(context) {
    if (isFileAllowlisted(context)) return {}

    return {
      Program(node) {
        const src = context.sourceCode.getText()

        const dialogRanges = findDialogRanges(src)
        if (dialogRanges.length === 0) return // no dialogs in this file → nothing to flag

        for (const { re, messageId } of VIOLATIONS) {
          // Clone the regex so we reset lastIndex for each call
          const pattern = new RegExp(re.source, 'g')
          let m
          while ((m = pattern.exec(src)) !== null) {
            if (!isInsideDialog(m.index, dialogRanges)) continue
            const loc = offsetToLoc(src, m.index)
            context.report({
              node,
              loc,
              messageId,
            })
          }
        }
      },
    }
  },
}
