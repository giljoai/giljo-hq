import { describe, it, expect } from 'vitest'
import { planTabFit } from './productTabFit'

const base = { gap: 6, fixedWidth: 36, moreWidth: 80 }

describe('planTabFit', () => {
  it('shows every tab when they all fit', () => {
    expect(planTabFit({ ...base, available: 1000, widths: [100, 100, 100], viewedIndex: 0 })).toEqual([0, 1, 2])
  })

  it('shows every tab when the strip has not been laid out yet', () => {
    expect(planTabFit({ ...base, available: 0, widths: [100, 100], viewedIndex: 1 })).toEqual([0, 1])
  })

  it('keeps tabs in order and stops at the first one that does not fit', () => {
    expect(planTabFit({ ...base, available: 400, widths: [100, 100, 100, 100], viewedIndex: 0 })).toEqual([0, 1])
  })

  it('always keeps the viewed tab, even when it sits at the end', () => {
    expect(planTabFit({ ...base, available: 400, widths: [100, 100, 100, 100], viewedIndex: 3 })).toEqual([0, 3])
  })

  it('keeps the viewed tab alone when nothing else fits', () => {
    expect(planTabFit({ ...base, available: 250, widths: [100, 100, 100], viewedIndex: 2 })).toEqual([2])
  })
})
