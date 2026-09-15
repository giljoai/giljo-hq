import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => {
  const productA = { id: 'prod-a', name: 'Alpha', is_active: true, is_default: false }
  const productB = { id: 'prod-b', name: 'Beta', is_active: true, is_default: false }
  const showToast = vi.fn()
  const setDefaultProduct = vi.fn().mockResolvedValue({ ...productA, is_default: true })
  const mockStore = {
    products: [productA, productB],
    activeProduct: productA,
    fetchProducts: vi.fn().mockResolvedValue(undefined),
    fetchActiveProduct: vi.fn().mockResolvedValue(true),
    fetchProductById: vi.fn().mockResolvedValue(null),
    setDefaultProduct,
  }
  return { productA, productB, showToast, setDefaultProduct, mockStore }
})

vi.mock('@/stores/products', () => ({ useProductStore: () => h.mockStore }))
vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({ fetchFieldToggleConfig: vi.fn().mockResolvedValue(undefined) }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.showToast }) }))
vi.mock('@/composables/useProductActivation', () => ({
  useProductActivation: () => ({ toggleProductActivation: vi.fn() }),
}))
vi.mock('@/composables/useProductSoftDelete', async () => {
  const { ref } = await import('vue')
  return {
    useProductSoftDelete: () => ({
      showDeletedProductsDialog: ref(false),
      deletedProducts: ref([]),
      restoringProductId: ref(null),
      purgingProductId: ref(null),
      purgingAllProducts: ref(false),
      loadDeletedProducts: vi.fn().mockResolvedValue(undefined),
      restoreProduct: vi.fn(),
      purgeDeletedProduct: vi.fn(),
      purgeAllDeletedProducts: vi.fn(),
    }),
  }
})
vi.mock('@/composables/useProductVisionUpload', async () => {
  const { ref } = await import('vue')
  return {
    useProductVisionUpload: () => ({
      uploadingVision: ref(false),
      uploadProgress: ref(0),
      visionUploadError: ref(null),
      existingVisionDocuments: ref([]),
      loadExistingVisionDocuments: vi.fn(),
      uploadVisionFilesOnAttach: vi.fn(),
      resetUploadState: vi.fn(),
    }),
  }
})
vi.mock('@/services/api', () => ({
  default: { visionDocuments: { listByProduct: vi.fn().mockResolvedValue({ data: [] }) } },
}))

import { createRouter, createMemoryHistory } from 'vue-router'
import ProductsView from './ProductsView.vue'
import ProductCard from '@/components/products/ProductCard.vue'

const productsRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/products', name: 'Products', component: { template: '<div />' } },
  ],
})

function mountView() {
  return mount(ProductsView, {
    shallow: true,
    global: { renderStubDefaultSlot: true, plugins: [productsRouter] },
  })
}

describe('ProductsView — Default control wiring (FE-9529)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches the resolved default alongside the product list on mount', async () => {
    mountView()
    await flushPromises()
    expect(h.mockStore.fetchActiveProduct).toHaveBeenCalled()
  })

  it('passes isDefault=true only to the card matching the RESOLVED default, not raw is_default', async () => {
    const wrapper = mountView()
    await flushPromises()

    const cards = wrapper.findAllComponents(ProductCard)
    const cardA = cards.find((c) => c.props('product').id === 'prod-a')
    const cardB = cards.find((c) => c.props('product').id === 'prod-b')

    expect(h.productA.is_default).toBe(false)
    expect(cardA.props('isDefault')).toBe(true)
    expect(cardB.props('isDefault')).toBe(false)
  })

  it('@set-default on a card calls productStore.setDefaultProduct with that product id', async () => {
    const wrapper = mountView()
    await flushPromises()

    const cards = wrapper.findAllComponents(ProductCard)
    const cardB = cards.find((c) => c.props('product').id === 'prod-b')
    cardB.vm.$emit('set-default', h.productB)
    await flushPromises()

    expect(h.setDefaultProduct).toHaveBeenCalledWith('prod-b')
    expect(h.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success', message: expect.stringContaining('default') }),
    )
  })

  it('shows an error toast when setDefaultProduct rejects', async () => {
    h.setDefaultProduct.mockRejectedValueOnce(new Error('network down'))
    const wrapper = mountView()
    await flushPromises()

    const cards = wrapper.findAllComponents(ProductCard)
    const cardB = cards.find((c) => c.props('product').id === 'prod-b')
    cardB.vm.$emit('set-default', h.productB)
    await flushPromises()

    expect(h.showToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
  })
})
