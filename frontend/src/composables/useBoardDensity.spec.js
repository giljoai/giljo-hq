import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useBoardDensity, BOARD_DENSITY_STORAGE_ITEM, BOARD_DENSITIES } from './useBoardDensity'

function memoryStorage() {
  const map = new Map()
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    clear: () => map.clear(),
  }
}

let originalStorage
beforeEach(() => {
  originalStorage = window.localStorage
  window.localStorage = memoryStorage()
})
afterEach(() => {
  window.localStorage = originalStorage
})

describe('useBoardDensity', () => {
  it('defaults to Compact (FE-9685)', () => {
    const { density, isCompact } = useBoardDensity()
    expect(density.value).toBe(BOARD_DENSITIES.COMPACT)
    expect(isCompact.value).toBe(true)
  })

  it('stores under a new key, so a choice made under the old rule does not carry over (FE-9685)', () => {
    expect(BOARD_DENSITY_STORAGE_ITEM).toBe('jobs.density.v2')
    window.localStorage.setItem('jobs.density', 'detailed')
    expect(useBoardDensity().density.value).toBe(BOARD_DENSITIES.COMPACT)
  })

  it('reads a remembered choice and writes a new one', () => {
    window.localStorage.setItem(BOARD_DENSITY_STORAGE_ITEM, 'compact')
    const { density, setDensity, isCompact } = useBoardDensity()
    expect(density.value).toBe('compact')
    expect(isCompact.value).toBe(true)
    setDensity('detailed')
    expect(window.localStorage.getItem(BOARD_DENSITY_STORAGE_ITEM)).toBe('detailed')
    expect(density.value).toBe('detailed')
  })

  it('ignores a value it does not know', () => {
    window.localStorage.setItem(BOARD_DENSITY_STORAGE_ITEM, 'huge')
    const { density, setDensity } = useBoardDensity()
    expect(density.value).toBe('compact')
    setDensity('tiny')
    expect(density.value).toBe('compact')
  })

  it('still works when storage throws (private window, blocked site data)', () => {
    window.localStorage = {
      getItem: vi.fn(() => {
        throw new Error('blocked')
      }),
      setItem: vi.fn(() => {
        throw new Error('blocked')
      }),
    }
    const { density, setDensity } = useBoardDensity()
    expect(density.value).toBe('compact')
    expect(() => setDensity('detailed')).not.toThrow()
    expect(density.value).toBe('detailed')
  })
})
