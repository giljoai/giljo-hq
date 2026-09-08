import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProductStore } from '@/stores/products'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: {
    products: {
      list: vi.fn(),
      get: vi.fn(),
      getDefault: vi.fn(),
      deactivate: vi.fn(),
    },
  },
}))

describe('Product Store - Active Product Behavior', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useProductStore()
  })

  it('fetchActiveProduct sets activeProduct to null when no active product', async () => {
    api.products.getDefault.mockResolvedValue({
      data: { has_active_product: false, product: null },
    })

    await store.fetchActiveProduct()

    expect(store.activeProduct).toBeNull()
  })

  it('fetchActiveProduct sets activeProduct when backend reports an active product', async () => {
    const active = { id: 'p1', name: 'Active P', is_active: true }
    api.products.getDefault.mockResolvedValue({
      data: { has_active_product: true, product: active },
    })

    await store.fetchActiveProduct()

    expect(store.activeProduct).toEqual(active)
  })

  it('deactivation flow updates store such that activeProduct becomes null after refresh', async () => {
    const active = { id: 'p1', name: 'Active P', is_active: true }
    store.activeProduct = active

    api.products.deactivate.mockResolvedValue({ data: { ...active, is_active: false } })
    api.products.getDefault.mockResolvedValue({
      data: { has_active_product: false, product: null },
    })

    await api.products.deactivate(active.id)
    await store.fetchActiveProduct()

    expect(store.activeProduct).toBeNull()
  })
})
