import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockGet = vi.fn()
const mockList = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      get: (...a) => mockGet(...a),
      list: (...a) => mockList(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

import { useProductStore } from './products'

describe('products store — FE-9121 productsById write-through', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetchProductById writes the full response into productsById', async () => {
    const store = useProductStore()
    mockGet.mockResolvedValue({ data: { id: 'p1', name: 'Alpha', vision_analysis_complete: true } })

    const result = await store.fetchProductById('p1')

    expect(result).toMatchObject({ id: 'p1', name: 'Alpha' })
    expect(store.getProductById('p1')).toMatchObject({ id: 'p1', name: 'Alpha', vision_analysis_complete: true })
  })

  it('syncs currentProduct when the fetched id IS the selected product', async () => {
    const store = useProductStore()
    store.$patch({ currentProductId: 'p1', currentProduct: { id: 'p1', name: 'stale' } })
    mockGet.mockResolvedValue({ data: { id: 'p1', name: 'fresh' } })

    await store.fetchProductById('p1')

    expect(store.currentProduct).toMatchObject({ id: 'p1', name: 'fresh' })
  })

  it('leaves currentProduct untouched when the fetched id is NOT the selected product', async () => {
    const store = useProductStore()
    store.$patch({ currentProductId: 'p-selected', currentProduct: { id: 'p-selected', name: 'selected' } })
    mockGet.mockResolvedValue({ data: { id: 'p-other', name: 'other' } })

    await store.fetchProductById('p-other')

    expect(store.currentProduct).toMatchObject({ id: 'p-selected', name: 'selected' })
    expect(store.getProductById('p-other')).toMatchObject({ id: 'p-other', name: 'other' })
  })

  it('getProductById returns null for an id with no cached entry', () => {
    const store = useProductStore()
    expect(store.getProductById('missing')).toBeNull()
    expect(store.getProductById(null)).toBeNull()
  })

  it('clearProductData empties productsById', async () => {
    const store = useProductStore()
    mockGet.mockResolvedValue({ data: { id: 'p1', name: 'Alpha' } })
    await store.fetchProductById('p1')
    expect(store.getProductById('p1')).not.toBeNull()

    store.clearProductData()

    expect(store.getProductById('p1')).toBeNull()
    expect(store.productsById).toEqual({})
  })
})
