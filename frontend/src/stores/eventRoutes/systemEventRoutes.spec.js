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

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      get: (...a) => mockGet(...a),
      list: (...a) => mockList(...a),
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
