import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const h = vi.hoisted(() => ({
  viewedProductId: null,
  listRuns: vi.fn(() => Promise.resolve({ data: [] })),
  getRun: vi.fn(() => Promise.resolve({ data: {} })),
}))

vi.mock('@/services/api', () => ({
  default: {
    sequenceRuns: {
      list: (...a) => h.listRuns(...a),
      get: (...a) => h.getRun(...a),
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


describe('sequenceRunStore — the open run does not survive a scoped hydrate (FE-9631)', () => {
  let store

  const foreignRun = () => ({
    id: 'run-yapper',
    project_ids: ['yapper-p1', 'yapper-p2'],
    resolved_order: ['yapper-p1', 'yapper-p2'],
    project_statuses: { 'yapper-p1': 'completed', 'yapper-p2': 'pending' },
    status: 'stalled',
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
    h.listRuns.mockClear()
    h.getRun.mockReset()
    h.getRun.mockResolvedValue({ data: foreignRun() })
    h.viewedProductId = null
  })

  it('clears the open run when the scoped hydrate no longer returns it', async () => {
    h.viewedProductId = 'prod-yapper'
    await store.fetchRun('run-yapper')
    expect(store.activeRun.id).toBe('run-yapper')

    h.viewedProductId = 'prod-hermes'
    h.listRuns.mockResolvedValueOnce({ data: [] })
    await store.hydrate()

    expect(store.activeRuns).toEqual([])
    expect(store.reviewPendingRun).toBeNull()
    expect(store.activeRun).toBeNull()
  })

  it('does not re-seed the election set from a run the scoped hydrate did not return', async () => {
    h.viewedProductId = 'prod-hermes'
    h.listRuns.mockResolvedValueOnce({ data: [] })
    await store.hydrate()

    await store.fetchRun('run-yapper')

    expect(store.activeRuns).toEqual([])
    expect(store.isProjectInActiveChain('yapper-p1')).toBe(false)
    expect(store.reviewPendingRun).toBeNull()
  })

  it('counter-case: a hydrate that DOES return the open run keeps it (cockpit on its own product)', async () => {
    h.viewedProductId = 'prod-yapper'
    await store.fetchRun('run-yapper')

    h.listRuns.mockResolvedValueOnce({ data: [foreignRun()] })
    await store.hydrate()

    expect(store.activeRun.id).toBe('run-yapper')
    expect(store.reviewPendingRun?.id).toBe('run-yapper')
    expect(store.isProjectInActiveChain('yapper-p1')).toBe(true)
  })

  it('counter-case: a terminal open run surfaced as review-pending by the scoped hydrate is kept (FE-9104)', async () => {
    h.viewedProductId = 'prod-yapper'
    await store.fetchRun('run-yapper')

    h.listRuns.mockResolvedValueOnce({ data: [{ ...foreignRun(), status: 'completed' }] })
    await store.hydrate()

    expect(store.activeRun.id).toBe('run-yapper')
    expect(store.reviewPendingById.has('run-yapper')).toBe(true)
    expect(store.reviewPendingRun?.id).toBe('run-yapper')
  })
})
