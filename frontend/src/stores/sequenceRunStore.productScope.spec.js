import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const h = vi.hoisted(() => ({
  viewedProductId: null,
  listRuns: vi.fn(() => Promise.resolve({ data: [] })),
  updateRun: vi.fn(() => Promise.resolve({ data: {} })),
}))

vi.mock('@/services/api', () => ({
  default: {
    sequenceRuns: {
      list: (...a) => h.listRuns(...a),
      update: (...a) => h.updateRun(...a),
    },
  },
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    get effectiveProductId() {
      return h.viewedProductId
    },
  }),
}))

import { useSequenceRunStore } from './sequenceRunStore'

describe('sequenceRunStore.hydrate — product scoping (FE-9627)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
    h.listRuns.mockClear()
    h.viewedProductId = null
  })

  it('sends the viewed product id as product_id', async () => {
    h.viewedProductId = 'prod-hermes'

    await store.hydrate()

    expect(h.listRuns).toHaveBeenCalledTimes(1)
    expect(h.listRuns.mock.calls[0][0]).toMatchObject({ product_id: 'prod-hermes' })
  })

  it('keeps the existing status + review-pending params alongside the scope', async () => {
    h.viewedProductId = 'prod-hermes'

    await store.hydrate()

    expect(h.listRuns.mock.calls[0][0]).toMatchObject({
      status: 'pending,running,stalled',
      include_review_pending: true,
    })
  })

  it('omits product_id entirely when no product is selected', async () => {
    await store.hydrate()

    expect(h.listRuns).toHaveBeenCalledTimes(1)
    expect(h.listRuns.mock.calls[0][0]).not.toHaveProperty('product_id')
  })
})

describe('sequenceRunStore — a run keeps the product the list read names', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.viewedProductId = null
  })

  it('hydrate keeps product_id, and a patch response without one does not erase it', async () => {
    const listed = { id: 'r1', status: 'running', project_ids: ['p1'], resolved_order: ['p1'], product_id: 'prod-b' }
    h.listRuns.mockResolvedValueOnce({ data: [listed] })
    const store = useSequenceRunStore()

    await store.hydrate(undefined, { allProducts: true })
    expect(store.runsById.get('r1').product_id).toBe('prod-b')

    const { product_id: _omitted, ...single } = listed
    h.updateRun.mockResolvedValueOnce({ data: single })
    await store.patchRun('r1', { locked: true })
    expect(store.runsById.get('r1').product_id).toBe('prod-b')
  })
})
