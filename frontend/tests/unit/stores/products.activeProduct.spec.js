import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProductStore } from '@/stores/products'
import api from '@/services/api'

// Mock project store (required by product store)
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    fetchProjects: vi.fn().mockResolvedValue([]),
  }),
}))

/**
 * Product Store - Active Product (Handover 0049)
 *
 * Post-refactor notes:
 * - fetchActiveProduct uses api.products.getDefault() (not api.products.list)
 * - getDefault returns { has_active_product: boolean, product: object|null }
 * - No separate activeProductLoading state (shared loading ref is NOT used by fetchActiveProduct)
 * - fetchActiveProduct catch block does NOT set store.error (only console.error)
 */
describe('Product Store - Active Product (Handover 0049)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('State Initialization', () => {
    it('initializes with activeProduct as null', () => {
      const store = useProductStore()
      expect(store.activeProduct).toBeNull()
    })

  })

  describe('fetchActiveProduct()', () => {
    it('fetches and stores active product', async () => {
      const mockProduct = {
        id: 1,
        name: 'TinyContacts',
        is_active: true
      }

      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: true, product: mockProduct }
      })

      const store = useProductStore()
      await store.fetchActiveProduct()

      expect(store.activeProduct).toEqual(mockProduct)
    })

    it('calls api.products.getDefault()', async () => {
      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: false, product: null }
      })

      const store = useProductStore()
      await store.fetchActiveProduct()

      expect(api.products.getDefault).toHaveBeenCalled()
    })

    it('sets activeProduct to null when no active products exist', async () => {
      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: false, product: null }
      })

      const store = useProductStore()
      await store.fetchActiveProduct()

      expect(store.activeProduct).toBeNull()
    })

    it('handles API errors by setting activeProduct to null', async () => {
      const error = new Error('API Error')
      api.products.getDefault.mockRejectedValue(error)

      const store = useProductStore()
      await store.fetchActiveProduct()

      expect(store.activeProduct).toBeNull()
      // Note: fetchActiveProduct does NOT set store.error on failure (only console.error)
    })

    it('stores first product from response', async () => {
      const mockProduct = { id: 1, name: 'First Active', is_active: true }

      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: true, product: mockProduct }
      })

      const store = useProductStore()
      await store.fetchActiveProduct()

      expect(store.activeProduct).toEqual(mockProduct)
    })
  })

  describe('clearProductData()', () => {
    it('clears activeProduct along with other data', async () => {
      const store = useProductStore()

      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: true, product: { id: 1, name: 'Active Product' } }
      })

      await store.fetchActiveProduct()
      expect(store.activeProduct).not.toBeNull()

      store.clearProductData()

      expect(store.activeProduct).toBeNull()
      expect(store.products).toEqual([])
      expect(store.currentProductId).toBeNull()
    })
  })

  describe('Integration with existing product functionality', () => {
    it('maintains activeProduct independently from currentProduct', async () => {
      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: true, product: { id: 1, name: 'Product 1', is_active: true } }
      })

      // Mock for setCurrentProduct flow
      api.products.list.mockResolvedValue({
        data: [
          { id: 1, name: 'Product 1', is_active: true },
          { id: 2, name: 'Product 2', is_active: false }
        ]
      })

      api.products.get.mockResolvedValue({
        data: { id: 2, name: 'Product 2' }
      })

      // api.products.metrics is optional (store uses optional chaining)
      // No need to mock it - the store handles undefined gracefully

      const store = useProductStore()

      await store.fetchActiveProduct()
      expect(store.activeProduct.name).toBe('Product 1')

      await store.setCurrentProduct(2)
      expect(store.currentProduct.name).toBe('Product 2')

      // activeProduct should remain unchanged
      expect(store.activeProduct.name).toBe('Product 1')
    })

    it('both states are independent during product operations', async () => {
      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: true, product: { id: 1, name: 'ActiveProduct' } }
      })

      const store = useProductStore()
      await store.fetchActiveProduct()

      const activeProductBefore = store.activeProduct

      // Simulate creating a product
      api.products.create.mockResolvedValue({
        data: { id: 2, name: 'NewProduct' }
      })

      await store.createProduct({ name: 'NewProduct' })

      // activeProduct should remain unchanged
      expect(store.activeProduct).toEqual(activeProductBefore)
    })
  })

  describe('Active Product Data Structure', () => {
    it('preserves complete product object structure', async () => {
      const mockProduct = {
        id: 123,
        name: 'CompleteProduct',
        is_active: true,
        description: 'Test description',
        created_at: '2025-01-01T00:00:00Z',
        config_data: { field1: 'value1' }
      }

      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: true, product: mockProduct }
      })

      const store = useProductStore()
      await store.fetchActiveProduct()

      expect(store.activeProduct).toEqual(mockProduct)
      expect(store.activeProduct.config_data).toEqual({ field1: 'value1' })
    })

    it('handles products with minimal data', async () => {
      const minimalProduct = {
        id: 1,
        name: 'Minimal',
        is_active: true
      }

      api.products.getDefault.mockResolvedValue({
        data: { has_active_product: true, product: minimalProduct }
      })

      const store = useProductStore()
      await store.fetchActiveProduct()

      expect(store.activeProduct).toEqual(minimalProduct)
    })
  })
})
