/**
 * useProductActivation.fe9502c.spec.js — FE-9502c
 *
 * Activation now OPENS a tab for the product instead of reassigning the
 * single `currentProductId` selection. Pre-tabs, `setCurrentProduct` was the
 * only way to scope a session to a product, so activating one always meant
 * "now I'm looking at this" — correct in a single-product UI. Under the
 * tabbed shell, forcing that same reassignment would silently switch
 * whatever tab the user already had open, which is the kind of surprise
 * ruling 3 (no auto-navigation) exists to forbid on a background event, and
 * activation itself is a deliberate user click so the same principle applies:
 * it should open/switch to ITS OWN tab, not hijack another one's identity.
 *
 * Edition scope: Both.
 */
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
