import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProductActivation } from './useProductActivation'
import { useProductStore } from '@/stores/products'
import api from '@/services/api'

describe('useProductActivation — FE-9502c opens a tab, does not reassign the single selection', () => {
  let loadProducts
  let productStore
  let openTabSpy

  beforeEach(() => {
    setActivePinia(createPinia())
    loadProducts = vi.fn(() => Promise.resolve())
    vi.clearAllMocks()

    productStore = useProductStore()
    openTabSpy = vi.spyOn(productStore, 'openTab').mockResolvedValue()
    vi.spyOn(productStore, 'setCurrentProduct').mockResolvedValue()
    vi.spyOn(productStore, 'fetchActiveProduct').mockResolvedValue(true)
  })

  it('toggleProductActivation calls openTab with the shown product, never setCurrentProduct', async () => {
    api.products.activate.mockResolvedValue({ data: { success: true } })

    const { toggleProductActivation } = useProductActivation(loadProducts)
    await toggleProductActivation({ id: 'prod-2', name: 'New Product', is_active: false })

    expect(openTabSpy).toHaveBeenCalledWith('prod-2')
    expect(productStore.setCurrentProduct).not.toHaveBeenCalled()
  })
})
