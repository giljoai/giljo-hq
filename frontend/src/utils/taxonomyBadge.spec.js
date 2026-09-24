import { describe, it, expect } from 'vitest'
import {
  taxonomyBadgeStyle,
  resolveTaxonomyColor,
  isReservedTaskAlias,
  isReservedHandoverAlias,
  isHandoverRow,
  DEFAULT_PROJECT_TYPE_COLOR,
} from '@/utils/taxonomyBadge'
import { TSK_TYPE_COLOR, HND_TYPE_COLOR } from '@/utils/constants'

describe('taxonomyBadgeStyle', () => {
  it('returns a 15% tint background and full-brightness foreground for a given hex', () => {
    const style = taxonomyBadgeStyle('#6DB3E4')
    expect(style).toEqual({
      backgroundColor: '#6DB3E426',
      color: '#6DB3E4',
    })
  })

  it('falls back to DEFAULT_PROJECT_TYPE_COLOR when color is empty/null/undefined', () => {
    const fallbackBg = `${DEFAULT_PROJECT_TYPE_COLOR}26`
    expect(taxonomyBadgeStyle(null)).toEqual({
      backgroundColor: fallbackBg,
      color: DEFAULT_PROJECT_TYPE_COLOR,
    })
    expect(taxonomyBadgeStyle(undefined)).toEqual({
      backgroundColor: fallbackBg,
      color: DEFAULT_PROJECT_TYPE_COLOR,
    })
    expect(taxonomyBadgeStyle('')).toEqual({
      backgroundColor: fallbackBg,
      color: DEFAULT_PROJECT_TYPE_COLOR,
    })
  })
})

describe('isReservedTaskAlias', () => {
  it('matches TSK-nnnn and legacy TSKnnnn aliases', () => {
    expect(isReservedTaskAlias('TSK-0042')).toBe(true)
    expect(isReservedTaskAlias('TSK-123456')).toBe(true)
    expect(isReservedTaskAlias('TSK0042')).toBe(true)
  })

  it('does not match non-TSK aliases or non-strings', () => {
    expect(isReservedTaskAlias('BE-0001')).toBe(false)
    expect(isReservedTaskAlias('FE-0042')).toBe(false)
    expect(isReservedTaskAlias('TSKX-0001')).toBe(false)
    expect(isReservedTaskAlias(null)).toBe(false)
    expect(isReservedTaskAlias(undefined)).toBe(false)
    expect(isReservedTaskAlias('')).toBe(false)
  })
})

describe('resolveTaxonomyColor', () => {
  it('returns the purple TSK color when the abbreviation is TSK', () => {
    expect(resolveTaxonomyColor({ abbreviation: 'TSK', color: '#123456' })).toBe(TSK_TYPE_COLOR)
  })

  it('returns the purple TSK color from a TSK-nnnn alias even with no color', () => {
    expect(resolveTaxonomyColor({ alias: 'TSK-0042' })).toBe(TSK_TYPE_COLOR)
  })

  it('returns the row color for a non-TSK type', () => {
    expect(resolveTaxonomyColor({ abbreviation: 'BE', alias: 'BE-0001', color: '#6DB3E4' })).toBe('#6DB3E4')
  })

  it('falls back to the default color when nothing resolves', () => {
    expect(resolveTaxonomyColor({})).toBe(DEFAULT_PROJECT_TYPE_COLOR)
    expect(resolveTaxonomyColor()).toBe(DEFAULT_PROJECT_TYPE_COLOR)
  })
})


describe('handover (HND) taxonomy', () => {
  it('resolves the HND color from the abbreviation', () => {
    expect(resolveTaxonomyColor({ abbreviation: 'HND', color: '#123456' })).toBe(HND_TYPE_COLOR)
  })

  it('resolves the HND color from an HND-nnnn alias alone', () => {
    expect(resolveTaxonomyColor({ alias: 'HND-9641' })).toBe(HND_TYPE_COLOR)
  })

  it('keeps HND and TSK visually distinct', () => {
    expect(HND_TYPE_COLOR).not.toBe(TSK_TYPE_COLOR)
  })

  it('does not mistake a project type that merely starts with those letters', () => {
    expect(isReservedHandoverAlias('HNDX-0001')).toBe(false)
    expect(isReservedHandoverAlias('HND-0001')).toBe(true)
    expect(isReservedHandoverAlias('HND0001')).toBe(true)
    expect(isReservedHandoverAlias(undefined)).toBe(false)
  })

  describe('isHandoverRow', () => {
    it('is true from either signal and false otherwise', () => {
      expect(isHandoverRow({ task_type: { abbreviation: 'HND' } })).toBe(true)
      expect(isHandoverRow({ taxonomy_alias: 'HND-9641' })).toBe(true)
      expect(isHandoverRow({ taxonomy_alias: 'TSK-0001' })).toBe(false)
      expect(isHandoverRow({})).toBe(false)
      expect(isHandoverRow(null)).toBe(false)
      expect(isHandoverRow(undefined)).toBe(false)
    })
  })

  describe('WCAG AA contrast on the dark theme (the only registered theme)', () => {
    const channel = (c) => {
      const v = c / 255
      return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
    }
    const luminance = (hex) => {
      const h = hex.replace('#', '')
      const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    }
    const over = (fg, bg, alpha) => {
      const [f, b] = [fg.replace('#', ''), bg.replace('#', '')]
      const out = [0, 2, 4].map((i) => {
        const fv = parseInt(f.slice(i, i + 2), 16)
        const bv = parseInt(b.slice(i, i + 2), 16)
        return Math.round(alpha * fv + (1 - alpha) * bv)
      })
      return `#${out.map((v) => v.toString(16).padStart(2, '0')).join('')}`
    }
    const ratio = (a, b) => {
      const [la, lb] = [luminance(a), luminance(b)]
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
    }

    const PANEL = '#12202e'

    it('the HND pill clears AA against its own badge tint', () => {
      const badgeBackground = over(HND_TYPE_COLOR, PANEL, 0.15)
      expect(ratio(HND_TYPE_COLOR, badgeBackground)).toBeGreaterThanOrEqual(4.5)
    })

    it('the HND pill clears AA against the bare panel', () => {
      expect(ratio(HND_TYPE_COLOR, PANEL)).toBeGreaterThanOrEqual(4.5)
    })

    it('the contrast maths can actually fail', () => {
      expect(ratio('#141f2b', PANEL)).toBeLessThan(4.5)
    })
  })
})
