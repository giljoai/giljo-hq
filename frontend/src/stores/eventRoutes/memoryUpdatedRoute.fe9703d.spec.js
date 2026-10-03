import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/api', () => {
  const apiMock = { products: { get: vi.fn(), list: vi.fn(), getMemoryEntries: vi.fn() } }
  return { api: apiMock, default: apiMock }
})

import { SYSTEM_EVENT_ROUTES } from './systemEventRoutes'
import { useProductStore } from '../products'
import { useMemoryStore } from '../memoryStore'

describe('product:memory:updated route', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('feeds the memory store only; the product store has no handler for it', async () => {
    const memoryStore = useMemoryStore()
    memoryStore.handleMemoryEntryWritten = vi.fn()
    const entry = { id: 'm1', title: 'Learned' }

    await SYSTEM_EVENT_ROUTES['product:memory:updated'].handler({ product_id: 'p1', entry })

    expect(memoryStore.handleMemoryEntryWritten).toHaveBeenCalledWith('p1', entry)
    expect(useProductStore().handleProductMemoryUpdated).toBeUndefined()
  })
})
