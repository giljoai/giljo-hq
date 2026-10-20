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
  showToast: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  default: { products: { list: h.list, get: h.get } },
}))
vi.mock('@/stores/projects', () => ({ useProjectStore: () => ({ fetchProjects: h.fetchProjects }) }))
vi.mock('@/stores/tasks', () => ({ useTaskStore: () => ({ fetchTasks: h.fetchTasks }) }))
vi.mock('@/stores/commHubStore', () => ({ useCommHubStore: () => ({ loadThreads: h.loadThreads }) }))
// A shared spy: the global useToast mock hands each caller a fresh one (tests/setup.js).
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.showToast }) }))

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

  // FE-9796: "Failed to fetch product: AxiosError: timeout" was followed by
  // "Product not found, switching to first available". Only a real not-found
  // may move the user to another product.
  describe('a failed read is not a not-found (FE-9796)', () => {
    const C = { id: 'prod-c', name: 'C' }
    const timeout = () => Object.assign(new Error('timeout of 30000ms exceeded'), { code: 'ECONNABORTED', isAxiosError: true })
    const http = (status) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data: {} } })
    const seen = { events: [] }
    const onEvent = (e) => seen.events.push(e.detail)
    const toasts = () => h.showToast.mock.calls.map((c) => c[0])

    // Viewing B; the user asks for C, whose read fails. A (the first product) reads fine,
    // so a wrong "not found" verdict would visibly land the user on A.
    async function viewingBThenAskForC(cError) {
      h.list.mockResolvedValue({ data: [A, B, C] })
      h.get.mockImplementation(async (id) => {
        if (id === 'prod-c') throw cError
        return { data: id === 'prod-a' ? A : B }
      })
      await store.setCurrentProduct('prod-b')
      vi.clearAllMocks()
      seen.events = []
      window.addEventListener('product-changed', onEvent)
      try {
        await store.setCurrentProduct('prod-c')
      } finally {
        window.removeEventListener('product-changed', onEvent)
      }
    }

    it.each([
      ['a timeout', timeout],
      ['a network error', () => Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })],
      ['a 500', () => http(500)],
    ])('%s keeps the current product, switches nowhere and tells the user', async (_label, makeError) => {
      await viewingBThenAskForC(makeError())
      expect(store.currentProductId).toBe('prod-b')
      expect(store.currentProduct).toEqual(B)
      expect(stored()).toEqual([])
      expect(refreshed()).toEqual({ projects: 0, tasks: [], threads: [] })
      expect(seen.events).toEqual([])
      expect(toasts()).toHaveLength(1)
      expect(toasts()[0].type).toBe('error')
    })

    it('a timeout reading the product list keeps the current product', async () => {
      await store.setCurrentProduct('prod-b')
      vi.clearAllMocks()
      store.products = []
      h.list.mockRejectedValue(timeout())
      await store.setCurrentProduct('prod-a')
      expect(store.currentProductId).toBe('prod-b')
      expect(stored()).toEqual([])
      expect(toasts()).toHaveLength(1)
    })

    it('a real 404 still falls back to the first product', async () => {
      await viewingBThenAskForC(http(404))
      expect(store.currentProductId).toBe('prod-a')
      expect(store.currentProduct).toEqual(A)
      expect(stored()).toEqual([['set', 'prod-a']])
      expect(seen.events).toEqual([{ productId: 'prod-a', product: A }])
      expect(toasts()).toEqual([])
    })
  })
})
