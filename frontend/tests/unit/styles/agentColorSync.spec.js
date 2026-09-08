/**
 * Test: Agent color sync invariant (FE-9129)
 *
 * There are four surfaces holding agent colors: agentColors.js (source of
 * truth), agent-colors.scss, design-tokens.scss, and main.scss. Before
 * codegen existed, these were hand-synced with a comment as the only
 * enforcement mechanism. This test makes drift impossible: it fails if any
 * surface's hex values diverge from agentColors.js.
 *
 * Pure static file parsing (readFileSync) — no DB, no module-level mutable
 * state, no ordering dependencies. Hex comparisons are case-insensitive
 * (JS uses uppercase, SCSS uses lowercase).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const agentColorsPath = resolve(__dirname, '../../../src/config/agentColors.js')
const agentColorsScssPath = resolve(__dirname, '../../../src/styles/agent-colors.scss')
const designTokensScssPath = resolve(__dirname, '../../../src/styles/design-tokens.scss')
const mainScssPath = resolve(__dirname, '../../../src/styles/main.scss')

// SCSS-side legacy naming for the two roles whose SCSS var name differs from
// the JS canonical role name. Preserve exactly — do not "fix" this asymmetry.
const CANONICAL_TO_SCSS_NAME = {
  orchestrator: 'orchestrator',
  analyzer: 'analyzer',
  implementer: 'implementor',
  documenter: 'researcher',
  reviewer: 'reviewer',
  tester: 'tester',
}

function parseAgentColorsJs() {
  const source = readFileSync(agentColorsPath, 'utf-8')
  const colors = {}
  const blockRe = /(\w+):\s*\{\s*hex:\s*'(#[0-9A-Fa-f]{6})'/g
  let match
  while ((match = blockRe.exec(source)) !== null) {
    const [, role, hex] = match
    if (CANONICAL_TO_SCSS_NAME[role]) {
      colors[role] = hex
    }
  }
  return colors
}

function parseAgentColorShades() {
  const source = readFileSync(agentColorsPath, 'utf-8')
  const shadesBlockMatch = source.match(/AGENT_COLOR_SHADES\s*=\s*\{([\s\S]*?)\n\}/)
  if (!shadesBlockMatch) return null
  const block = shadesBlockMatch[1]
  const shades = {}
  const roleBlockRe = /(\w+):\s*\{\s*dark:\s*'(#[0-9A-Fa-f]{6})',\s*light:\s*'(#[0-9A-Fa-f]{6})'/g
  let match
  while ((match = roleBlockRe.exec(block)) !== null) {
    const [, role, dark, light] = match
    shades[role] = { dark, light }
  }
  return shades
}

function extractRootBlock(source) {
  const rootMatch = source.match(/:root\s*\{([\s\S]*?)\n\}/)
  return rootMatch ? rootMatch[1] : ''
}

function parseScssVars(block) {
  const vars = {}
  const varRe = /--([\w-]+):\s*([^;]+);/g
  let match
  while ((match = varRe.exec(block)) !== null) {
    vars[match[1]] = match[2].trim()
  }
  return vars
}

function hexToRgbaTinted(hex) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, 0.15)`
}

const jsColors = parseAgentColorsJs()
const canonicalRoles = Object.keys(CANONICAL_TO_SCSS_NAME)

describe('agentColorSync', () => {
  it('parsed six canonical roles from agentColors.js', () => {
    expect(canonicalRoles.every((role) => jsColors[role])).toBe(true)
    expect(Object.keys(jsColors)).toHaveLength(6)
  })

  describe('agent-colors.scss', () => {
    const scssSource = readFileSync(agentColorsScssPath, 'utf-8')
    const rootVars = parseScssVars(extractRootBlock(scssSource))

    it.each(canonicalRoles)('%s primary matches agentColors.js (case-insensitive)', (role) => {
      const scssName = CANONICAL_TO_SCSS_NAME[role]
      const primary = rootVars[`agent-${scssName}-primary`]
      expect(primary).toBeDefined()
      expect(primary.toLowerCase()).toBe(jsColors[role].toLowerCase())
    })

    it.each(canonicalRoles)('%s tinted equals rgba(r, g, b, 0.15) of primary', (role) => {
      const scssName = CANONICAL_TO_SCSS_NAME[role]
      const tinted = rootVars[`agent-${scssName}-tinted`]
      expect(tinted).toBe(hexToRgbaTinted(jsColors[role]))
    })

    it('canonical implementer vars alias the implementor (legacy) vars', () => {
      expect(rootVars['agent-implementer-primary']).toBe('var(--agent-implementor-primary)')
      expect(rootVars['agent-implementer-dark']).toBe('var(--agent-implementor-dark)')
      expect(rootVars['agent-implementer-light']).toBe('var(--agent-implementor-light)')
      expect(rootVars['agent-implementer-tinted']).toBe('var(--agent-implementor-tinted)')
    })

    it('canonical documenter vars alias the researcher (legacy) vars', () => {
      expect(rootVars['agent-documenter-primary']).toBe('var(--agent-researcher-primary)')
      expect(rootVars['agent-documenter-dark']).toBe('var(--agent-researcher-dark)')
      expect(rootVars['agent-documenter-light']).toBe('var(--agent-researcher-light)')
      expect(rootVars['agent-documenter-tinted']).toBe('var(--agent-researcher-tinted)')
    })

    it.each(canonicalRoles)('%s has -dark and -light vars', (role) => {
      const scssName = CANONICAL_TO_SCSS_NAME[role]
      const dark = rootVars[`agent-${scssName}-dark`]
      const light = rootVars[`agent-${scssName}-light`]
      expect(dark).toMatch(/^#[0-9a-fA-F]{6}$/)
      expect(light).toMatch(/^#[0-9a-fA-F]{6}$/)
    })

    it.each(canonicalRoles)('%s -dark/-light match AGENT_COLOR_SHADES when present', (role) => {
      const shades = parseAgentColorShades()
      if (!shades) return // Step 2 hasn't landed yet — existence/format already asserted above.
      const scssName = CANONICAL_TO_SCSS_NAME[role]
      const dark = rootVars[`agent-${scssName}-dark`]
      const light = rootVars[`agent-${scssName}-light`]
      expect(dark.toLowerCase()).toBe(shades[role].dark.toLowerCase())
      expect(light.toLowerCase()).toBe(shades[role].light.toLowerCase())
    })
  })

  describe('design-tokens.scss', () => {
    const source = readFileSync(designTokensScssPath, 'utf-8')

    it.each(canonicalRoles)('$color-agent-%s matches agentColors.js (case-insensitive)', (role) => {
      const scssName = CANONICAL_TO_SCSS_NAME[role]
      const re = new RegExp(`\\$color-agent-${scssName}:\\s*(#[0-9A-Fa-f]{6})`)
      const match = source.match(re)
      expect(match).not.toBeNull()
      expect(match[1].toLowerCase()).toBe(jsColors[role].toLowerCase())
    })
  })

  describe('main.scss', () => {
    const source = readFileSync(mainScssPath, 'utf-8')
    const rootVars = parseScssVars(extractRootBlock(source))
    const mirrorKeys = Object.keys(rootVars).filter((k) => k.startsWith('color-agent-'))

    // This set is NOT "there must be exactly N mirrors" (BE-5039/FE-5041) — it
    // tracks which agent color tokens a PROJECT STATUS actually uses via
    // ProjectStatus.color_token (see the backend contract test
    // tests/contract/test_project_status_color_tokens.py, which requires the
    // reverse: every status color_token MUST be mirrored here). Together the
    // two tests say "mirror exactly the tokens statuses use, no more, no
    // fewer." Grow this set only when a NEW status starts using a token;
    // do not "complete" it to all six roles just because they exist in
    // agentColors.js — the remaining unmirrored role(s) stay unmirrored
    // until a status needs them. FE-9508 added the fifth entry
    // (color-agent-orchestrator) because ProjectStatus.SUPERSEDED now uses
    // it (operator ruling 2026-08-26: tan reads as archived/replaced).
    const expectedMirrors = {
      'color-agent-implementer': 'implementer',
      'color-agent-analyzer': 'analyzer',
      'color-agent-researcher': 'documenter',
      'color-agent-reviewer': 'reviewer',
      'color-agent-orchestrator': 'orchestrator',
    }

    it('has exactly the project-status-used --color-agent-* mirrors, no more, no fewer', () => {
      expect(mirrorKeys.sort()).toEqual(Object.keys(expectedMirrors).sort())
    })

    it.each(Object.entries(expectedMirrors))('%s matches agentColors.js %s hex (case-insensitive)', (scssKey, role) => {
      expect(rootVars[scssKey].toLowerCase()).toBe(jsColors[role].toLowerCase())
    })
  })
})
