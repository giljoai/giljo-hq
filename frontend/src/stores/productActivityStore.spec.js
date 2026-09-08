import { describe, expect, it, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProductActivityStore } from './productActivityStore'

describe('productActivityStore (FE-9502d)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('starts with zero total and no per-product counts', () => {
    const store = useProductActivityStore()
    expect(store.totalCount).toBe(0)
    expect(store.getCount('prod-1')).toBe(0)
    expect(store.activeProductIds).toEqual([])
  })

  it('recordActivity increments the count for that product only', () => {
    const store = useProductActivityStore()
    store.recordActivity('prod-1')
    store.recordActivity('prod-1')
    store.recordActivity('prod-2')

    expect(store.getCount('prod-1')).toBe(2)
    expect(store.getCount('prod-2')).toBe(1)
    expect(store.getCount('prod-3')).toBe(0)
    expect(store.totalCount).toBe(3)
  })

  it('recordActivity with a falsy product id is a no-op (the conductor no-product exception)', () => {
    const store = useProductActivityStore()
    store.recordActivity(null)
    store.recordActivity(undefined)
    store.recordActivity('')

    expect(store.totalCount).toBe(0)
    expect(store.activeProductIds).toEqual([])
  })

  it('clearActivity removes the count for that product without touching others', () => {
    const store = useProductActivityStore()
    store.recordActivity('prod-1')
    store.recordActivity('prod-2')
    store.recordActivity('prod-2')

    store.clearActivity('prod-1')

    expect(store.getCount('prod-1')).toBe(0)
    expect(store.getCount('prod-2')).toBe(2)
    expect(store.totalCount).toBe(2)
    expect(store.activeProductIds).toEqual(['prod-2'])
  })

  it('clearActivity on an unknown product id is a no-op', () => {
    const store = useProductActivityStore()
    store.recordActivity('prod-1')

    store.clearActivity('does-not-exist')

    expect(store.getCount('prod-1')).toBe(1)
  })

  it('$reset clears every product', () => {
    const store = useProductActivityStore()
    store.recordActivity('prod-1')
    store.recordActivity('prod-2')

    store.$reset()

    expect(store.totalCount).toBe(0)
    expect(store.activeProductIds).toEqual([])
  })
})
