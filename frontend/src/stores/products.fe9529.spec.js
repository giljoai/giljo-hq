/**
 * products.fe9529.spec.js — FE-9529
 *
 * The Default-product write path: setDefaultProduct() and the
 * delete-clears-default follow-up read.
 *
 * - setDefaultProduct calls the ONE server write (POST /set-default, already
 *   atomic server-side: ProductLifecycleService.set_default_product clears
 *   any previous default in the SAME call) then mirrors that single-default
 *   guarantee into the local list immediately, and refreshes the RESOLVED
 *   default (activeProduct) rather than assuming the write response IS the
 *   resolution.
 * - deleteProduct: a deleted product's is_default is cleared server-side
 *   (FE-9524's product_lifecycle_service.py); if the deleted row WAS the
 *   resolved default, the store must re-read rather than keep pointing
 *   activeProduct at a soft-deleted row.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockList = vi.fn()
const mockSetDefault = vi.fn()
const mockGetDefault = vi.fn()
const mockDelete = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      list: (...a) => mockList(...a),
      setDefault: (...a) => mockSetDefault(...a),
      getDefault: (...a) => mockGetDefault(...a),
      delete: (...a) => mockDelete(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

import { useProductStore } from './products'

const PRODUCT_A = { id: 'prod-a', name: 'Alpha', is_active: true, is_default: true }
const PRODUCT_B = { id: 'prod-b', name: 'Beta', is_active: true, is_default: false }

describe('products store — setDefaultProduct (FE-9529)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('calls the set-default endpoint with the product id', async () => {
    const store = useProductStore()
    store.$patch({ products: [PRODUCT_A, PRODUCT_B] })
    mockSetDefault.mockResolvedValue({ data: { ...PRODUCT_B, is_default: true } })
    mockGetDefault.mockResolvedValue({ data: { has_active_product: true, product: { ...PRODUCT_B, is_default: true } } })

    await store.setDefaultProduct('prod-b')

    expect(mockSetDefault).toHaveBeenCalledWith('prod-b')
  })

  it('mirrors the single-default guarantee locally: the new default is set, every other row that was flagged loses it', async () => {
    const store = useProductStore()
    store.$patch({ products: [PRODUCT_A, PRODUCT_B] })
    mockSetDefault.mockResolvedValue({ data: { ...PRODUCT_B, is_default: true } })
    mockGetDefault.mockResolvedValue({ data: { has_active_product: true, product: { ...PRODUCT_B, is_default: true } } })

    await store.setDefaultProduct('prod-b')

    const a = store.products.find((p) => p.id === 'prod-a')
    const b = store.products.find((p) => p.id === 'prod-b')
    expect(a.is_default).toBe(false)
    expect(b.is_default).toBe(true)
  })

  it('refreshes the RESOLVED default (activeProduct) via a separate read, not just the write response', async () => {
    const store = useProductStore()
    store.$patch({ products: [PRODUCT_A, PRODUCT_B] })
    mockSetDefault.mockResolvedValue({ data: { ...PRODUCT_B, is_default: true } })
    mockGetDefault.mockResolvedValue({ data: { has_active_product: true, product: { ...PRODUCT_B, is_default: true } } })

    await store.setDefaultProduct('prod-b')

    expect(mockGetDefault).toHaveBeenCalled()
    expect(store.activeProduct).toMatchObject({ id: 'prod-b' })
  })

  it('propagates a rejection and does not touch local state', async () => {
    const store = useProductStore()
    store.$patch({ products: [PRODUCT_A, PRODUCT_B] })
    mockSetDefault.mockRejectedValue(new Error('network down'))

    await expect(store.setDefaultProduct('prod-b')).rejects.toThrow('network down')

    expect(store.products.find((p) => p.id === 'prod-a').is_default).toBe(true)
    expect(store.products.find((p) => p.id === 'prod-b').is_default).toBe(false)
  })
})

describe('products store — deleting the resolved default re-reads it (FE-9529)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('re-fetches the default when the deleted product WAS the resolved default', async () => {
    const store = useProductStore()
    store.$patch({ products: [PRODUCT_A, PRODUCT_B], activeProduct: PRODUCT_A })
    mockDelete.mockResolvedValue({ data: { success: true } })
    mockGetDefault.mockResolvedValue({ data: { has_active_product: true, product: PRODUCT_B } })

    await store.deleteProduct('prod-a')

    expect(mockGetDefault).toHaveBeenCalled()
    expect(store.activeProduct).toMatchObject({ id: 'prod-b' })
  })

  it('does NOT re-fetch the default when the deleted product was some other row', async () => {
    const store = useProductStore()
    store.$patch({ products: [PRODUCT_A, PRODUCT_B], activeProduct: PRODUCT_A })
    mockDelete.mockResolvedValue({ data: { success: true } })

    await store.deleteProduct('prod-b')

    expect(mockGetDefault).not.toHaveBeenCalled()
    expect(store.activeProduct).toMatchObject({ id: 'prod-a' })
  })
})
