/**
 * systemEventRoutes.spec.js — FE-9121
 *
 * vision:analysis_complete must refresh productsById[payload.product_id]
 * unconditionally — including when that product is NOT the globally
 * selected one (the create-wizard case the ProductForm gate exists for).
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockGet = vi.fn()
const mockList = vi.fn()
const mockTasksList = vi.fn()
const mockGetMemoryEntries = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      get: (...a) => mockGet(...a),
      list: (...a) => mockList(...a),
      getMemoryEntries: (...a) => mockGetMemoryEntries(...a),
    },
    tasks: {
      list: (...a) => mockTasksList(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

import { SYSTEM_EVENT_ROUTES } from './systemEventRoutes'
import { useProductStore } from '../products'
import { useNotificationStore } from '../notifications'
import { useTaskStore } from '../tasks'
import { useMemoryStore } from '../memoryStore'

describe('systemEventRoutes — FE-9121 vision:analysis_complete write-through', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: [] })
    mockTasksList.mockResolvedValue({ data: [] })
  })

  it('refreshes productsById[product_id] even when NOT the selected product', async () => {
    const productStore = useProductStore()
    productStore.$patch({ currentProductId: 'p-other-selected', currentProduct: { id: 'p-other-selected' } })
    mockGet.mockResolvedValue({ data: { id: 'p-new', vision_analysis_complete: true } })

    await SYSTEM_EVENT_ROUTES['vision:analysis_complete'].handler({
      product_id: 'p-new',
      fields_written: 3,
    })

    expect(mockGet).toHaveBeenCalledWith('p-new')
    expect(productStore.getProductById('p-new')).toMatchObject({ id: 'p-new', vision_analysis_complete: true })
    // The non-selected product must be left alone.
    expect(productStore.currentProductId).toBe('p-other-selected')
  })

  it('refreshes the products list and dispatches the vision-analysis-complete window event', async () => {
    mockGet.mockResolvedValue({ data: { id: 'p-new', vision_analysis_complete: true } })
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

    await SYSTEM_EVENT_ROUTES['vision:analysis_complete'].handler({ product_id: 'p-new' })

    expect(mockList).toHaveBeenCalledTimes(1)
    const dispatched = dispatchSpy.mock.calls.map((c) => c[0]).find((e) => e.type === 'vision-analysis-complete')
    expect(dispatched).toBeDefined()
    expect(dispatched.detail).toMatchObject({ product_id: 'p-new' })
    dispatchSpy.mockRestore()
  })

  it('still fires the notification and dispatches the window event when the store refresh throws (FE-9166)', async () => {
    const productStore = useProductStore()
    productStore.fetchProducts = vi.fn(() => Promise.reject(new Error('boom')))
    productStore.fetchProductById = vi.fn(() => Promise.reject(new Error('boom')))
    const notificationStore = useNotificationStore()
    const addSpy = vi.spyOn(notificationStore, 'addNotification')
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

    await SYSTEM_EVENT_ROUTES['vision:analysis_complete'].handler({ product_id: 'p-new' })

    expect(addSpy).toHaveBeenCalledTimes(1)
    const dispatched = dispatchSpy.mock.calls
      .map((c) => c[0])
      .find((e) => e.type === 'vision-analysis-complete')
    expect(dispatched).toBeDefined()
    expect(dispatched.detail).toMatchObject({ product_id: 'p-new' })
    dispatchSpy.mockRestore()
    warnSpy.mockRestore()
  })

  it('no-ops the store refresh when payload has no product_id', async () => {
    await SYSTEM_EVENT_ROUTES['vision:analysis_complete'].handler({})

    expect(mockGet).not.toHaveBeenCalled()
    expect(mockList).not.toHaveBeenCalled()
  })

  it('still fires the notification even without a product_id', async () => {
    const notificationStore = useNotificationStore()
    const addSpy = vi.spyOn(notificationStore, 'addNotification')

    await SYSTEM_EVENT_ROUTES['vision:analysis_complete'].handler({})

    expect(addSpy).toHaveBeenCalledTimes(1)
  })
})

describe('systemEventRoutes — FE-9274 P2 task:updated live refresh', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockTasksList.mockResolvedValue({ data: [{ id: 't-1', status: 'in_progress' }] })
  })

  it('is registered as a route (the client-side drop the backend implementer flagged)', () => {
    expect(SYSTEM_EVENT_ROUTES['task:updated']).toBeDefined()
    expect(typeof SYSTEM_EVENT_ROUTES['task:updated'].handler).toBe('function')
  })

  it('refetches the task list on task:updated, mirroring task:created', async () => {
    const taskStore = useTaskStore()
    expect(taskStore.tasks).toEqual([])

    await SYSTEM_EVENT_ROUTES['task:updated'].handler({ task_id: 't-1', status: 'in_progress' })

    expect(mockTasksList).toHaveBeenCalledTimes(1)
    expect(taskStore.tasks).toEqual([{ id: 't-1', status: 'in_progress' }])
  })
})

describe('systemEventRoutes — FE-9501c (D9) task events replay the filter, not a bare fetch', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockTasksList.mockResolvedValue({ data: [] })
  })

  it('task:created replays the last fetchTasks() params instead of refetching paramless', async () => {
    const taskStore = useTaskStore()
    await taskStore.fetchTasks({ status: 'blocked', priority: 'high' })
    mockTasksList.mockClear()

    await SYSTEM_EVENT_ROUTES['task:created'].handler({})

    expect(mockTasksList).toHaveBeenCalledWith({ status: 'blocked', priority: 'high' })
  })

  it('task:updated replays the last fetchTasks() params instead of refetching paramless', async () => {
    const taskStore = useTaskStore()
    await taskStore.fetchTasks({ filter_type: 'all_tasks' })
    mockTasksList.mockClear()

    await SYSTEM_EVENT_ROUTES['task:updated'].handler({ task_id: 't-1' })

    expect(mockTasksList).toHaveBeenCalledWith({ filter_type: 'all_tasks' })
  })
})

describe('systemEventRoutes — FE-9501c (D8) product:memory:updated also feeds memoryStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockGetMemoryEntries.mockResolvedValue({ data: { entries: [] } })
  })

  it('upserts the written entry into memoryStore when that product is loaded', async () => {
    mockGetMemoryEntries.mockResolvedValueOnce({ data: { entries: [{ id: 'e1', summary: 'existing' }] } })
    const memoryStore = useMemoryStore()
    await memoryStore.fetchMemoryEntries('prod-1')

    await SYSTEM_EVENT_ROUTES['product:memory:updated'].handler({
      product_id: 'prod-1',
      entry: { id: 'e2', summary: 'new write' },
    })

    expect(memoryStore.entries.map((e) => e.id).sort()).toEqual(['e1', 'e2'])
  })

  it('does not touch memoryStore for a product it has not loaded', async () => {
    const memoryStore = useMemoryStore()

    await SYSTEM_EVENT_ROUTES['product:memory:updated'].handler({
      product_id: 'prod-unloaded',
      entry: { id: 'e2', summary: 'new write' },
    })

    expect(memoryStore.entries).toHaveLength(0)
  })
})

describe('systemEventRoutes — FE-9501c (D10) product:created / product:updated', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: [] })
    mockGet.mockResolvedValue({ data: { id: 'p-1', name: 'Renamed' } })
  })

  it('product:created refreshes the products list', async () => {
    await SYSTEM_EVENT_ROUTES['product:created'].handler({ product_id: 'p-1', name: 'New Product' })
    expect(mockList).toHaveBeenCalledTimes(1)
  })

  it('product:updated refreshes both the list and the specific product', async () => {
    await SYSTEM_EVENT_ROUTES['product:updated'].handler({ product_id: 'p-1' })
    expect(mockList).toHaveBeenCalledTimes(1)
    expect(mockGet).toHaveBeenCalledWith('p-1')
  })
})
