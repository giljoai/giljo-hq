/**
 * FE-9365a — the button-shape standard is enforced by mechanism, not by memory.
 *
 * The rule: NOTHING in this app is a circle except status dots and fully-rounded
 * pills. Buttons are squares with rounded corners.
 *
 * Why a test and not a review convention: the app had drifted into three shapes
 * for the same control — circular icon buttons on Projects, a rectangular button
 * on Tasks, plain text buttons on the Hub — precisely because nothing failed when
 * a screen improvised. A standard that only lives in a document is a standard that
 * decays. This test makes adding a new circle a build failure unless it is
 * deliberately classified as an indicator.
 *
 * Two assertions:
 *   1. The global rule still exists in main.scss and still out-specifies Vuetify's
 *      `.v-btn--icon { border-radius: 50% }`.
 *   2. Every hand-written `border-radius: 50%` in the tree belongs to an
 *      allowlisted selector — a dot, ring, orb, badge or decorative glow. A new
 *      one fails here with the file and selector named, so the author has to
 *      decide consciously whether it is an indicator or a button.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'fs'
import { resolve, join } from 'path'

const SRC = resolve(__dirname, '../../src')

/**
 * Selectors permitted to be circular. Every entry is an INDICATOR or decoration —
 * a status light, a step marker, a ring, a badge or a glow — never something the
 * user clicks. Adding a button here defeats the point of the test.
 */
const CIRCULAR_ALLOWLIST = new Set([
  // Status lights and dots — the standing exception to the square rule.
  'nav-orb',
  'status-dot',
  'status-indicator',
  'tab-status-dot',
  'rail-dot',
  'rail-sub-dot',
  'dir-rail-dot',
  'rm-product-dot',
  'hero-dot',
  // FE-9365c: the Hub card's agent status dot. Colour and ring come from
  // useAgentStatusDot (the Jobs board's vocabulary); it is an indicator, never clicked.
  '__pill-dot',
  // FE-9365e: the same dot again, as the legend's swatch. It has to be round for the
  // legend to be explaining the thing the card actually draws.
  '__dot',
  // FE-9365d: the status dot on a To-dropdown row — same indicator, same rule.
  '__option-dot',
  // Notification bell state indicators (colour dots on the bell, not the bell).
  'notification-bell--error',
  'notification-bell--warning',
  'notification-bell--unread',
  // Step markers and completion rings in the setup/onboarding flows.
  'cert-step-number',
  'step-marker',
  'complete-ring',
  'tool-card-ring',
  'hero-check',
  // FE-9569: the pulsing halo ring around the tutorial prompt screen's
  // waiting dot -- an indicator (agent-status pulse), never clicked.
  'waiting-dot-ring',
  // Badges and decorative glows.
  'msg-badge',
  'account-status-badge',
  'hero-mascot-glow',
])

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '__tests__') continue
      walk(full, out)
    } else if (/\.(vue|scss)$/.test(entry.name)) {
      out.push(full)
    }
  }
  return out
}

/**
 * Resolve the nearest preceding selector for a given line — the last line above it
 * that opens a block and names a class. Good enough for this codebase's flat SCSS;
 * it never has to be a real parser, it only has to name the thing so a human can
 * classify it.
 */
function selectorFor(lines, index) {
  for (let i = index; i >= 0; i--) {
    // Matches both a plain class (`.nav-orb {`) and SCSS parent-suffix nesting
    // (`&__pill-dot {`). The nested form matters: without it the walk skips past the
    // real owner and reports the enclosing block instead, so the failure message names
    // `.thread-card` when the circle actually belongs to `&__pill-dot` — and a gate
    // that misnames the offender sends the next author to the wrong line.
    const m = lines[i].match(/^\s*[&.]{1,2}([a-zA-Z_][\w-]*)[^{]*\{\s*$/)
    if (m) return m[1]
  }
  return '(unresolved)'
}

describe('FE-9365a — button shape standard', () => {
  it('main.scss still carries the global icon-button rule at winning specificity', () => {
    const css = readFileSync(join(SRC, 'styles/main.scss'), 'utf8')

    // Two classes, so it beats Vuetify's single-class `.v-btn--icon` no matter how
    // the bundler orders the stylesheets. A single-class override would be a
    // coin-flip decided by build order — see the comment block in main.scss.
    expect(css).toMatch(/\.v-btn\.v-btn--icon\s*\{[^}]*border-radius:\s*\$border-radius-default/)
  })

  it('no button is circular — every `border-radius: 50%` is an allowlisted indicator', () => {
    const offenders = []

    for (const file of walk(SRC)) {
      const lines = readFileSync(file, 'utf8').split(/\r?\n/)
      lines.forEach((line, i) => {
        if (!/border-radius:\s*50%/.test(line)) return
        // Prose mentioning the rule is not the rule. main.scss documents WHY the
        // standard exists and quotes Vuetify's `border-radius: 50%` while doing so;
        // matching our own explanation would make the test fail on its own docs.
        if (/^\s*(\/\/|\/\*|\*)/.test(line)) return
        const selector = selectorFor(lines, i)
        if (!CIRCULAR_ALLOWLIST.has(selector)) {
          offenders.push(`${file.replace(SRC, 'src')}:${i + 1} → .${selector}`)
        }
      })
    }

    expect(
      offenders,
      'New circular element(s) found. If it is a status dot or decoration, add its ' +
        'selector to CIRCULAR_ALLOWLIST. If a user clicks it, it is a button — give it ' +
        '`border-radius: $border-radius-default` instead.\n' +
        offenders.join('\n'),
    ).toEqual([])
  })

  it('no component opts back into a circle via the Vuetify `rounded` prop', () => {
    const offenders = []
    for (const file of walk(SRC)) {
      const src = readFileSync(file, 'utf8')
      if (/rounded=["']circle["']/.test(src)) offenders.push(file.replace(SRC, 'src'))
    }
    expect(offenders).toEqual([])
  })
})
