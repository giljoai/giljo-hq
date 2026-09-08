/**
 * products.fe9502c.spec.js — FE-9502c, server-backed since FE-9524/D1
 *
 * The tabbed product shell's store-level state: open (shown) tabs
 * (openTab/switchTab/closeTab) and a fixed bug in initializeFromStorage
 * discovered while extending it (product ids are UUID strings; the old
 * `parseInt(...)` comparison could never match one, so a persisted selection
 * was silently discarded on every reload). Reproduced as a failing test below
 * (museum rule) before the fix.
 *
 * FE-9524/D1: `openProductIds` is no longer a UI-local ref backed by
 * localStorage -- it is derived from `products[].is_active`, and
 * openTab/closeTab are server writes (api.products.activate/deactivate).
 *
 * Two real tabs, both open at once, is the condition this file exists to
 * prove -- a strip that only ever renders one tab proves nothing.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockGet = vi.fn()
const mockList = vi.fn()
const mockGetDefault = vi.fn()
const mockSetDefault = vi.fn()
const mockActivate = vi.fn()
const mockDeactivate = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      get: (...a) => mockGet(...a),
      list: (...a) => mockList(...a),
      getDefault: (...a) => mockGetDefault(...a),
      setDefault: (...a) => mockSetDefault(...a),
      activate: (...a) => mockActivate(...a),
      deactivate: (...a) => mockDeactivate(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

vi.mock('./projects', () => ({
  useProjectStore: () => ({ fetchProjects: vi.fn().mockResolvedValue() }),
}))
vi.mock('./tasks', () => ({
  useTaskStore: () => ({ fetchTasks: vi.fn().mockResolvedValue() }),
}))
const mockLoadThreads = vi.fn().mockResolvedValue()
vi.mock('./commHubStore', () => ({
  useCommHubStore: () => ({ loadThreads: mockLoadThreads }),
}))

import { useProductStore } from './products'

const PRODUCT_A = { id: 'a1111111-0000-0000-0000-000000000001', name: 'Product A', is_active: false }
const PRODUCT_B = { id: 'b2222222-0000-0000-0000-000000000002', name: 'Product B', is_active: false }

/** Mutates the shared fixtures' is_active so the next fetchProducts()/list() reflects it -- mirrors the server persisting an activate/deactivate write. */
function showOnServer(id) {
  ;[PRODUCT_A, PRODUCT_B].forEach((p) => {
    if (p.id === id) p.is_active = true
  })
}
function hideOnServer(id) {
  ;[PRODUCT_A, PRODUCT_B].forEach((p) => {
    if (p.id === id) p.is_active = false
  })
}

describe('products store — FE-9502c/FE-9524 open (shown) tabs', () => {
  let backing

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    PRODUCT_A.is_active = false
    PRODUCT_B.is_active = false
    mockList.mockImplementation(() => Promise.resolve({ data: [PRODUCT_A, PRODUCT_B] }))
    mockGet.mockImplementation((id) =>
      Promise.resolve({ data: [PRODUCT_A, PRODUCT_B].find((p) => p.id === id) || null }),
    )
    mockGetDefault.mockResolvedValue({ data: { has_active_product: false, product: null } })
    mockActivate.mockImplementation((id) => {
      showOnServer(id)
      return Promise.resolve({ data: null })
    })
    mockDeactivate.mockImplementation((id) => {
      hideOnServer(id)
      return Promise.resolve({ data: null })
    })

    backing = new Map()
    window.localStorage = {
      getItem: (k) => (backing.has(k) ? backing.get(k) : null),
      setItem: (k, v) => backing.set(k, String(v)),
      removeItem: (k) => backing.delete(k),
      clear: () => backing.clear(),
    }
  })

  it('openTab shows a second real tab alongside the first -- both stay shown', async () => {
    const store = useProductStore()
    await store.openTab(PRODUCT_A.id)
    await store.openTab(PRODUCT_B.id)

    expect(mockActivate).toHaveBeenCalledWith(PRODUCT_A.id)
    expect(mockActivate).toHaveBeenCalledWith(PRODUCT_B.id)
    expect(store.openProductIds).toEqual([PRODUCT_A.id, PRODUCT_B.id])
    expect(store.openProductTabs.map((p) => p.id)).toEqual([PRODUCT_A.id, PRODUCT_B.id])
    // The viewed tab followed the most recent open.
    expect(store.currentProductId).toBe(PRODUCT_B.id)
  })

  it('switchTab moves the viewed product without hiding the other tab', async () => {
    const store = useProductStore()
    await store.openTab(PRODUCT_A.id)
    await store.openTab(PRODUCT_B.id)

    await store.switchTab(PRODUCT_A.id)

    expect(store.currentProductId).toBe(PRODUCT_A.id)
    expect(store.openProductIds).toEqual([PRODUCT_A.id, PRODUCT_B.id])
  })

  // FE-9528: the Hub ignored the viewed product tab because switchTab
  // re-scoped projects and tasks but never the Hub. Same reload contract as
  // fetchProjects()/fetchTasks() above.
  it('switchTab re-scopes the Hub to the newly viewed product', async () => {
    const store = useProductStore()
    await store.openTab(PRODUCT_A.id)
    await store.openTab(PRODUCT_B.id)

    await store.switchTab(PRODUCT_A.id)

    expect(mockLoadThreads).toHaveBeenCalledWith({ product_id: PRODUCT_A.id })
  })

  it('closeTab hides a tab on the server and the local list drops it', async () => {
    const store = useProductStore()
    await store.openTab(PRODUCT_A.id)
    await store.openTab(PRODUCT_B.id)

    await store.closeTab(PRODUCT_A.id)

    expect(mockDeactivate).toHaveBeenCalledWith(PRODUCT_A.id)
    expect(store.openProductIds).toEqual([PRODUCT_B.id])
  })

  it('closing the VIEWED tab switches the view to its neighbor', async () => {
    const store = useProductStore()
    await store.openTab(PRODUCT_A.id)
    await store.openTab(PRODUCT_B.id)
    // Viewed tab is B (opened last). Close it.
    await store.closeTab(PRODUCT_B.id)

    expect(store.currentProductId).toBe(PRODUCT_A.id)
    expect(store.openProductIds).toEqual([PRODUCT_A.id])
  })

  it('refuses to close the last remaining tab', async () => {
    const store = useProductStore()
    await store.openTab(PRODUCT_A.id)

    await store.closeTab(PRODUCT_A.id)

    expect(mockDeactivate).not.toHaveBeenCalled()
    expect(store.openProductIds).toEqual([PRODUCT_A.id])
    expect(store.currentProductId).toBe(PRODUCT_A.id)
  })

  it('re-opening an already-shown tab just switches to it, does not re-activate', async () => {
    const store = useProductStore()
    await store.openTab(PRODUCT_A.id)
    await store.openTab(PRODUCT_B.id)
    mockActivate.mockClear()

    await store.openTab(PRODUCT_A.id)

    expect(mockActivate).not.toHaveBeenCalled()
    expect(store.openProductIds).toEqual([PRODUCT_A.id, PRODUCT_B.id])
    expect(store.currentProductId).toBe(PRODUCT_A.id)
  })
})

describe('products store — FE-9502c initializeFromStorage restores a UUID selection', () => {
  let backing

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    PRODUCT_A.is_active = false
    PRODUCT_B.is_active = false
    mockList.mockImplementation(() => Promise.resolve({ data: [PRODUCT_A, PRODUCT_B] }))
    mockGet.mockImplementation((id) =>
      Promise.resolve({ data: [PRODUCT_A, PRODUCT_B].find((p) => p.id === id) || null }),
    )
    mockGetDefault.mockResolvedValue({ data: { has_active_product: false, product: null } })
    mockActivate.mockImplementation((id) => {
      showOnServer(id)
      return Promise.resolve({ data: null })
    })
    mockDeactivate.mockImplementation((id) => {
      hideOnServer(id)
      return Promise.resolve({ data: null })
    })

    backing = new Map()
    window.localStorage = {
      getItem: (k) => (backing.has(k) ? backing.get(k) : null),
      setItem: (k, v) => backing.set(k, String(v)),
      removeItem: (k) => backing.delete(k),
      clear: () => backing.clear(),
    }
  })

  it('restores the exact persisted product, not products[0] (regression: parseInt on a UUID)', async () => {
    // Product B is NOT first in the list -- if the bug's parseInt(uuid)=>NaN
    // mismatch fires, initializeFromStorage silently falls back to
    // products[0] (Product A) instead.
    window.localStorage.setItem('currentProductId', PRODUCT_B.id)

    const store = useProductStore()
    await store.initializeFromStorage()

    expect(store.currentProductId).toBe(PRODUCT_B.id)
  })

  it('FE-9524: migrates a persisted multi-tab localStorage set to server is_active, then clears the key', async () => {
    window.localStorage.setItem('currentProductId', PRODUCT_A.id)
    window.localStorage.setItem(
      'openProductTabIds',
      JSON.stringify([PRODUCT_A.id, PRODUCT_B.id, 'deleted-product-id']),
    )

    const store = useProductStore()
    await store.initializeFromStorage()

    expect(mockActivate).toHaveBeenCalledWith(PRODUCT_A.id)
    expect(mockActivate).toHaveBeenCalledWith(PRODUCT_B.id)
    expect(store.openProductIds.slice().sort()).toEqual([PRODUCT_A.id, PRODUCT_B.id].sort())
    expect(window.localStorage.getItem('openProductTabIds')).toBeNull()
  })

  it('FE-9524: a second browser with no local migration key just sees the server-shown set', async () => {
    // Simulates: product A was already shown server-side (e.g. shown from
    // another machine, or by a prior migration run in THIS browser).
    PRODUCT_A.is_active = true
    window.localStorage.setItem('currentProductId', PRODUCT_A.id)
    // No 'openProductTabIds' key at all.

    const store = useProductStore()
    await store.initializeFromStorage()

    expect(mockActivate).not.toHaveBeenCalled()
    expect(store.openProductIds).toEqual([PRODUCT_A.id])
  })

  it('FE-9524: migration ensures the restored viewed tab is shown even if it was not in the stored tab set', async () => {
    window.localStorage.setItem('currentProductId', PRODUCT_A.id)
    window.localStorage.setItem('openProductTabIds', JSON.stringify([PRODUCT_B.id]))

    const store = useProductStore()
    await store.initializeFromStorage()

    expect(mockActivate).toHaveBeenCalledWith(PRODUCT_A.id)
    expect(store.openProductIds).toContain(PRODUCT_A.id)
  })
})

/**
 * FE-9529 hole: ProductRepository.get_default_product's
 * sole-shown-product fallback fires ONLY when exactly one shown product
 * exists and nothing has is_default persisted. Showing a SECOND product
 * silently erases that fallback -- the tenant had a working default a moment
 * ago and now has none, with nothing telling them.
 *
 * The fix (promoting the implicit default before it is lost) lives in
 * ProductLifecycleService.activate_product -- the ONE owning writer for "a
 * product becomes shown" (dual-door rule: REST and any future MCP tool both
 * land there). It does NOT belong in this store: a client-side-only fix
 * would leave every other caller of POST /products/{id}/activate exposed to
 * the exact hole this exists to close. See
 * tests/services/test_fe9529_activate_promotes_implicit_default.py and
 * tests/integration/test_fe9529_activate_endpoint_promotes_default.py for
 * the real (backend) coverage. This store's contract is unchanged: openTab
 * calls activate() and nothing else, proven by the pre-existing "opens a
 * second real tab" test above.
 */
