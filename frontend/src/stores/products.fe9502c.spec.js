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
    PRODUCT_A.is_active = true
    window.localStorage.setItem('currentProductId', PRODUCT_A.id)

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

