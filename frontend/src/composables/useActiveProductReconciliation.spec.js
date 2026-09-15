import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { effectScope } from 'vue'

const PRODUCT_A = { id: 'prod-hermes', name: 'Hermes' }
const PRODUCT_B = { id: 'prod-auditor', name: 'Codebase_Auditor' }

const mockGetDefault = vi.fn()
const mockGet = vi.fn()
const mockList = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      list: (...a) => mockList(...a),
      get: (...a) => mockGet(...a),
      getDefault: (...a) => mockGetDefault(...a),
    },
    tasks: { list: vi.fn(() => Promise.resolve({ data: [] })) },
  }
  return { api: apiMock, default: apiMock }
})

const mockUnregisterResync = vi.fn()
const mockRegisterReconnectResync = vi.fn(() => mockUnregisterResync)
vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: (...a) => mockRegisterReconnectResync(...a),
}))

import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useActiveProductReconciliation } from './useActiveProductReconciliation'

function setVisibility(state) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  })
}

function createStaleSession() {
  const projectStore = useProjectStore()
  projectStore.fetchProjects = vi.fn(() => Promise.resolve())
  const taskStore = useTaskStore()
  taskStore.fetchTasks = vi.fn(() => Promise.resolve())

  const products = useProductStore()
  products.$patch({
    activeProduct: PRODUCT_A,
    currentProductId: PRODUCT_A.id,
    currentProduct: PRODUCT_A,
    openProductIds: [PRODUCT_A.id],
  })
  return { products, projectStore, taskStore }
}

describe('FE-9412/FE-9502c — activeProduct heals on focus, the viewed tab never moves', () => {
  let scope

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    setVisibility('visible')

    mockGetDefault.mockResolvedValue({
      data: { has_active_product: true, product: PRODUCT_B },
    })
    mockList.mockResolvedValue({ data: [PRODUCT_A, PRODUCT_B] })
    mockGet.mockImplementation((id) =>
      Promise.resolve({ data: id === PRODUCT_B.id ? PRODUCT_B : PRODUCT_A }),
    )

    scope = effectScope()
  })

  afterEach(() => {
    scope?.stop()
  })

  it('refreshes the displayed activeProduct when the tab becomes visible again', async () => {
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    setVisibility('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_B.id }))

    expect(mockGetDefault).toHaveBeenCalled()
  })

  it('does NOT reassign the viewed tab (currentProductId) even though activeProduct diverges', async () => {
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_B.id }))

    expect(session.products.currentProductId).toBe(PRODUCT_A.id)
    expect(session.projectStore.fetchProjects).not.toHaveBeenCalled()
  })

  it('re-validates on window focus', async () => {
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    window.dispatchEvent(new Event('focus'))
    await vi.waitFor(() => expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_B.id }))

    expect(mockGetDefault).toHaveBeenCalled()
    expect(session.products.currentProductId).toBe(PRODUCT_A.id)
  })

  it('does not re-validate when the tab goes HIDDEN', async () => {
    createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    setVisibility('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    await Promise.resolve()

    expect(mockGetDefault).not.toHaveBeenCalled()
  })

  it('re-validates on a WebSocket reconnect (the other way a session learns it missed something)', async () => {
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    expect(mockRegisterReconnectResync).toHaveBeenCalledTimes(1)
    const resync = mockRegisterReconnectResync.mock.calls[0][0]
    await resync()

    expect(mockGetDefault).toHaveBeenCalled()
    expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_B.id })
    expect(session.products.currentProductId).toBe(PRODUCT_A.id)
  })

  it('a FAILED re-validation leaves the displayed activeProduct exactly as it was', async () => {
    mockGetDefault.mockRejectedValue(new Error('network down'))
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(mockGetDefault).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_A.id })
    expect(session.products.currentProductId).toBe(PRODUCT_A.id)
    expect(session.projectStore.fetchProjects).not.toHaveBeenCalled()
  })

  it('detaches its listeners and its resync registration on teardown', async () => {
    createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    scope.stop()

    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('focus'))
    await Promise.resolve()

    expect(mockGetDefault).not.toHaveBeenCalled()
    expect(mockUnregisterResync).toHaveBeenCalledTimes(1)
  })
})
