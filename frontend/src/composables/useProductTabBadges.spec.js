import { describe, expect, it, vi } from 'vitest'
import { withProductActivityBadges } from './useProductTabBadges'

describe('withProductActivityBadges (FE-9502d)', () => {
  it('attaches badgeCount for every background tab', () => {
    const tabs = [
      { id: 'p1', name: 'Product 1' },
      { id: 'p2', name: 'Product 2' },
    ]
    const getCount = vi.fn((id) => (id === 'p2' ? 3 : 0))

    const result = withProductActivityBadges(tabs, 'p1', getCount)

    expect(result).toEqual([
      { id: 'p1', name: 'Product 1', badgeCount: 0 },
      { id: 'p2', name: 'Product 2', badgeCount: 3 },
    ])
  })

  it('forces badgeCount to 0 for the viewed tab even if getCount would return nonzero', () => {
    const tabs = [{ id: 'p1', name: 'Product 1' }]
    const getCount = vi.fn(() => 5)

    const result = withProductActivityBadges(tabs, 'p1', getCount)

    expect(result[0].badgeCount).toBe(0)
    expect(getCount).not.toHaveBeenCalledWith('p1')
  })

  it('returns an empty array for a non-array input', () => {
    expect(withProductActivityBadges(null, 'p1', () => 0)).toEqual([])
    expect(withProductActivityBadges(undefined, 'p1', () => 0)).toEqual([])
  })

  it('does not mutate the original tab objects', () => {
    const tab = { id: 'p1', name: 'Product 1' }
    const tabs = [tab]

    withProductActivityBadges(tabs, 'p2', () => 4)

    expect(tab).toEqual({ id: 'p1', name: 'Product 1' })
  })
})
