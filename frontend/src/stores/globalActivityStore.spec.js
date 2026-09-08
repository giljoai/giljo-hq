import { describe, expect, it, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGlobalActivityStore } from './globalActivityStore'

describe('globalActivityStore (FE-9501b, D5)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('starts with zero total and no per-project counts', () => {
    const store = useGlobalActivityStore()
    expect(store.totalCount).toBe(0)
    expect(store.getCount('proj-1')).toBe(0)
    expect(store.activeProjectIds).toEqual([])
  })

  it('recordActivity increments the count for that project only', () => {
    const store = useGlobalActivityStore()
    store.recordActivity('proj-1')
    store.recordActivity('proj-1')
    store.recordActivity('proj-2')

    expect(store.getCount('proj-1')).toBe(2)
    expect(store.getCount('proj-2')).toBe(1)
    expect(store.getCount('proj-3')).toBe(0)
    expect(store.totalCount).toBe(3)
  })

  it('recordActivity with a falsy project id is a no-op', () => {
    const store = useGlobalActivityStore()
    store.recordActivity(null)
    store.recordActivity(undefined)
    store.recordActivity('')

    expect(store.totalCount).toBe(0)
    expect(store.activeProjectIds).toEqual([])
  })

  it('clearActivity removes the count for that project without touching others', () => {
    const store = useGlobalActivityStore()
    store.recordActivity('proj-1')
    store.recordActivity('proj-2')
    store.recordActivity('proj-2')

    store.clearActivity('proj-1')

    expect(store.getCount('proj-1')).toBe(0)
    expect(store.getCount('proj-2')).toBe(2)
    expect(store.totalCount).toBe(2)
    expect(store.activeProjectIds).toEqual(['proj-2'])
  })

  it('clearActivity on an unknown project id is a no-op', () => {
    const store = useGlobalActivityStore()
    store.recordActivity('proj-1')

    store.clearActivity('does-not-exist')

    expect(store.getCount('proj-1')).toBe(1)
  })

  it('$reset clears every project', () => {
    const store = useGlobalActivityStore()
    store.recordActivity('proj-1')
    store.recordActivity('proj-2')

    store.$reset()

    expect(store.totalCount).toBe(0)
    expect(store.activeProjectIds).toEqual([])
  })
})
