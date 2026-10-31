import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { contrastRatio, ensureContrast, compositeOver, accessibleTintedStyle, BADGE_SURFACE } from '@/utils/colorUtils'
import { taxonomyBadgeStyle } from '@/utils/taxonomyBadge'
import { STATUS_COLORS } from '@/utils/statusConfig'
import { TEXT_MUTED, TEXT_SECONDARY } from '@/config/colorTokens'
import { DEFAULT_PROJECT_TYPE_COLOR, PROJECT_TYPE_COLOR_SWATCHES } from '@/utils/constants'

const RAISED = '#12202e'
const ELEVATED = '#1e3147'
const AA = 4.5

const src = (p) => readFileSync(resolve(__dirname, '..', p), 'utf8')

describe('contrast helpers', () => {
  it('white on black is 21:1', () => {
    expect(contrastRatio('#ffffff', '#000000')).toBeCloseTo(21, 1)
  })
  it('ensureContrast keeps a passing colour untouched and lifts a failing one', () => {
    expect(ensureContrast('#ffffff', RAISED, AA)).toBe('#ffffff')
    const lifted = ensureContrast('#607D8B', compositeOver('#607D8B', RAISED, 0.15), AA)
    expect(contrastRatio(lifted, compositeOver('#607D8B', RAISED, 0.15))).toBeGreaterThanOrEqual(AA)
  })
})

describe('taxonomy badge text', () => {
  const colors = [DEFAULT_PROJECT_TYPE_COLOR, ...PROJECT_TYPE_COLOR_SWATCHES]
  for (const base of [RAISED, ELEVATED]) {
    it(`every type colour reaches ${AA}:1 on its own 15% tint over ${base}`, () => {
      for (const c of colors) {
        const style = taxonomyBadgeStyle(c)
        const bg = compositeOver(c, base, 0.15)
        expect(contrastRatio(style.color, bg), `${c}`).toBeGreaterThanOrEqual(AA)
      }
    })
  }
  it('keeps the hue family: a colour that already passes is returned unchanged', () => {
    expect(taxonomyBadgeStyle('#A0D0F0').color).toBe('#A0D0F0')
  })
})

describe('status and muted text tokens', () => {
  it('Decommissioned status text passes on the raised panel', () => {
    expect(contrastRatio(STATUS_COLORS.DECOMMISSIONED, RAISED)).toBeGreaterThanOrEqual(AA)
  })
  it('SCSS decommissioned token mirrors the JS value', () => {
    const m = src('styles/design-tokens.scss').match(/\$color-status-decommissioned:\s*(#[0-9a-f]{6})/i)
    expect(m[1].toLowerCase()).toBe(STATUS_COLORS.DECOMMISSIONED.toLowerCase())
  })
  it('--text-secondary passes on the elevated surface (hero-sub, hovered thread card)', () => {
    expect(contrastRatio(TEXT_SECONDARY, ELEVATED)).toBeGreaterThanOrEqual(AA)
  })
  it('--text-muted passes AA on every surface it sits on', () => {
    const hovered = compositeOver('#ffffff', ELEVATED, 0.04)
    for (const bg of [RAISED, ELEVATED, hovered]) {
      expect(contrastRatio(TEXT_MUTED, bg), bg).toBeGreaterThanOrEqual(AA)
    }
  })
  it('--text-muted stays visibly dimmer than --text-secondary', () => {
    expect(contrastRatio(TEXT_MUTED, RAISED)).toBeLessThan(contrastRatio(TEXT_SECONDARY, RAISED))
  })
  it('the CSS variable, the JS token and the fallbacks share one source', () => {
    const scss = src('styles/design-tokens.scss').match(/\$text-muted:\s*(#[0-9a-f]{6})/i)[1]
    expect(scss.toLowerCase()).toBe(TEXT_MUTED.toLowerCase())
    expect(src('styles/main.scss')).toContain('--text-muted: #{$text-muted};')
  })
})

describe('tinted status badges (StatusBadge)', () => {
  const root = src('styles/main.scss')
  const tokens = [...root.matchAll(/--(color-status-[a-z-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]])
  const extra = [['text-muted', TEXT_MUTED], ['cancelled red', '#f44336']]

  for (const [name, hex] of [...tokens, ...extra]) {
    it(`${name} (${hex}) text reaches ${AA}:1 on its own 15% tint over the badge surface`, () => {
      const style = accessibleTintedStyle(hex)
      expect(contrastRatio(style.color, compositeOver(hex, BADGE_SURFACE, 0.15))).toBeGreaterThanOrEqual(AA)
    })
  }
  it('found the status tokens it is meant to cover', () => {
    expect(tokens.length).toBeGreaterThanOrEqual(3)
  })
  it('.in-chain-pill derives its tint from the token, not a hardcoded rgba', () => {
    const rule = src('views/projects/ProjectsTable.vue').match(/\.in-chain-pill\s*\{[^}]*\}/)[0]
    expect(rule).toContain('color-mix(in srgb, var(--text-muted)')
    expect(rule).not.toMatch(/rgba\(\s*136/)
  })
})
