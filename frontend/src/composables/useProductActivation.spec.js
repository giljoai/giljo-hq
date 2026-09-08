import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProductActivation } from './useProductActivation'
import api from '@/services/api'

describe('useProductActivation', () => {
  let loadProducts

  beforeEach(() => {
    setActivePinia(createPinia())
    loadProducts = vi.fn(() => Promise.resolve())
    vi.clearAllMocks()
  })

  it('toggleProductActivation hides a shown product (is_active true)', async () => {
    const { toggleProductActivation } = useProductActivation(loadProducts)

    api.products.deactivate.mockResolvedValue({ data: { success: true } })

    await toggleProductActivation({ id: 'prod-1', name: 'Shown Product', is_active: true })

    expect(api.products.deactivate).toHaveBeenCalledWith('prod-1')
    expect(api.products.activate).not.toHaveBeenCalled()
    expect(loadProducts).toHaveBeenCalled()
  })

  it('toggleProductActivation shows a hidden product (is_active false)', async () => {
    const { toggleProductActivation } = useProductActivation(loadProducts)

    api.products.activate.mockResolvedValue({ data: { success: true } })

    await toggleProductActivation({ id: 'prod-2', name: 'Hidden Product', is_active: false })

    expect(api.products.activate).toHaveBeenCalledWith('prod-2')
    expect(api.products.deactivate).not.toHaveBeenCalled()
    expect(loadProducts).toHaveBeenCalled()
  })

  it('toggleProductActivation does not throw on API failure', async () => {
    const { toggleProductActivation } = useProductActivation(loadProducts)

    api.products.activate.mockRejectedValue(new Error('Network error'))

    await expect(
      toggleProductActivation({ id: 'prod-2', name: 'Product', is_active: false }),
    ).resolves.toBeUndefined()
    expect(loadProducts).not.toHaveBeenCalled()
  })

  it('FE-9529: the composable exposes only the toggle -- the activation-warning dialog state/actions are deleted, not just inert', () => {
    const result = useProductActivation(loadProducts)

    expect(Object.keys(result)).toEqual(['toggleProductActivation'])
  })
})
