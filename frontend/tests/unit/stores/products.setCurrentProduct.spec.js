/**
 * Characterization of products.setCurrentProduct: which product becomes
 * current, what is persisted, which product-scoped stores are refreshed and
 * which event is dispatched, for the found, not-found and empty cases.
 *
 * Edition Scope: CE
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const h = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  fetchProjects: vi.fn(),
  fetchTasks: vi.fn(),
  loadThreads: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  default: { products: { list: h.list, get: h.get } },
}))
vi.mock('@/stores/projects', () => ({ useProjectStore: () => ({ fetchProjects: h.fetchProjects }) }))
vi.mock('@/stores/tasks', () => ({ useTaskStore: () => ({ fetchTasks: h.fetchTasks }) }))
vi.mock('@/stores/commHubStore', () => ({ useCommHubStore: () => ({ loadThreads: h.loadThreads }) }))

import { useProductStore } from '@/stores/products'

const A = { id: 'prod-a', name: 'A' }
const B = { id: 'prod-b', name: 'B' }

describe('products.setCurrentProduct', () => {
  let store
  let events

  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    store = useProductStore()
    events = []
    window.addEventListener('product-changed', (e) => events.push(e.detail), { once: true })
    h.list.mockResolvedValue({ data: [A, B] })
    h.get.mockImplementation(async (id) => ({ data: { A, B }[id === 'prod-a' ? 'A' : id === 'prod-b' ? 'B' : 'X'] ?? null }))
  })

  const stored = () => [
    ...localStorage.setItem.mock.calls.filter((c) => c[0] === 'currentProductId').map((c) => ['set', c[1]]),
    ...localStorage.removeItem.mock.calls.filter((c) => c[0] === 'currentProductId').map(() => ['remove']),
  ]

  const refreshed = () => ({
    projects: h.fetchProjects.mock.calls.length,
    tasks: h.fetchTasks.mock.calls,
    threads: h.loadThreads.mock.calls,
  })

  it('a known product becomes current, is persisted and re-scopes the stores', async () => {
    await store.setCurrentProduct('prod-b')
    expect(store.currentProductId).toBe('prod-b')
    expect(store.currentProduct).toEqual(B)
    expect(stored()).toEqual([['set', 'prod-b']])
    expect(refreshed()).toEqual({
      projects: 1,
      tasks: [[{ product_id: 'prod-b' }]],
      threads: [[{ product_id: 'prod-b' }]],
    })
    expect(events).toEqual([{ productId: 'prod-b', product: B }])
  })

  it('an unknown product falls back to the first product with the same side effects', async () => {
    await store.setCurrentProduct('prod-gone')
    expect(store.currentProductId).toBe('prod-a')
    expect(store.currentProduct).toEqual(A)
    expect(stored()).toEqual([['set', 'prod-a']])
    expect(refreshed()).toEqual({
      projects: 1,
      tasks: [[{ product_id: 'prod-a' }]],
      threads: [[{ product_id: 'prod-a' }]],
    })
    expect(events).toEqual([{ productId: 'prod-a', product: A }])
  })

  it('null selects the first product', async () => {
    await store.setCurrentProduct(null)
    expect(store.currentProductId).toBe('prod-a')
    expect(events).toEqual([{ productId: 'prod-a', product: A }])
  })

  it('no products clears the selection and refreshes nothing', async () => {
    h.list.mockResolvedValue({ data: [] })
    await store.setCurrentProduct('prod-a')
    expect(store.currentProductId).toBeNull()
    expect(store.currentProduct).toBeNull()
    expect(stored()).toEqual([['remove']])
    expect(refreshed()).toEqual({ projects: 0, tasks: [], threads: [] })
    expect(events).toEqual([])
  })

  it('unknown product whose fallback also fails leaves the selection untouched', async () => {
    h.get.mockResolvedValue({ data: null })
    await store.setCurrentProduct('prod-gone')
    expect(store.currentProductId).toBeNull()
    expect(stored()).toEqual([])
    expect(refreshed()).toEqual({ projects: 0, tasks: [], threads: [] })
    expect(events).toEqual([])
  })
})
