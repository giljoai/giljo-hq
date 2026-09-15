import { describe, it, expect } from 'vitest'
import {
  taxonomyBadgeStyle,
  resolveTaxonomyColor,
  isReservedTaskAlias,
  DEFAULT_PROJECT_TYPE_COLOR,
} from '@/utils/taxonomyBadge'
import { TSK_TYPE_COLOR } from '@/utils/constants'

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
