import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => {
  const leanProduct = {
    id: 'prod-1',
    name: 'My Product',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
    is_active: false,
    project_count: 5,
    task_count: 3,
    unfinished_projects: 2,
    vision_documents_count: 0,
    vision_analysis_complete: false,
    vision_summary: { doc_count: 0, chunked_count: 0, chunk_total: 0, embedded_count: 0 },
  }
  const fullProduct = {
    ...leanProduct,
    tech_stack: { programming_languages: 'Python' },
    architecture: { primary_pattern: 'layered' },
    test_config: { coverage_target: 90 },
  }
  const fetchProductById = vi.fn().mockResolvedValue(fullProduct)
  const showToast = vi.fn()
  const mockStore = {
    products: [leanProduct],
    activeProduct: null,
    fetchProducts: vi.fn().mockResolvedValue(undefined),
    fetchActiveProduct: vi.fn().mockResolvedValue(true),
    fetchProductById,
    setDefaultProduct: vi.fn().mockResolvedValue(null),
  }
  return { leanProduct, fullProduct, fetchProductById, showToast, mockStore }
})

const { leanProduct, fullProduct, fetchProductById, showToast } = h

vi.mock('@/stores/products', () => ({ useProductStore: () => h.mockStore }))
vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({ fetchFieldToggleConfig: vi.fn().mockResolvedValue(undefined) }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.showToast }) }))
vi.mock('@/composables/useProductActivation', () => ({
  useProductActivation: () => ({
    toggleProductActivation: vi.fn(),
  }),
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
      loadExistingVisionDocuments: vi.fn().mockResolvedValue(undefined),
      uploadVisionFilesOnAttach: vi.fn(),
      resetUploadState: vi.fn(),
    }),
  }
})
vi.mock('@/services/api', () => ({
  default: {
    products: {
      list: vi.fn().mockResolvedValue({ data: [h.leanProduct] }),
      get: vi.fn().mockResolvedValue({ data: h.fullProduct }),
    },
    visionDocuments: { listByProduct: vi.fn().mockResolvedValue({ data: [] }) },
  },
}))

import { createRouter, createMemoryHistory } from 'vue-router'
import ProductsView from './ProductsView.vue'
import ProductCard from '@/components/products/ProductCard.vue'
import ProductForm from '@/components/products/ProductForm.vue'

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

describe('ProductsView.editProduct (BE-6066 P4)', () => {
  beforeEach(() => {
    fetchProductById.mockClear()
    showToast.mockClear()
  })

  it('fetches the full product on Edit and passes it to ProductForm', async () => {
    const wrapper = mountView()
    await flushPromises()

    const card = wrapper.findComponent(ProductCard)
    expect(card.exists()).toBe(true)

    card.vm.$emit('edit', leanProduct)
    await flushPromises()

    expect(fetchProductById).toHaveBeenCalledWith('prod-1')

    const form = wrapper.findComponent(ProductForm)
    expect(form.props('product')).toEqual(fullProduct)
    expect(form.props('product').tech_stack.programming_languages).toBe('Python')
    expect(showToast).not.toHaveBeenCalled()
  })

  it('falls back to the lean row and warns if the detail fetch fails', async () => {
    fetchProductById.mockResolvedValueOnce(null)
    const wrapper = mountView()
    await flushPromises()

    wrapper.findComponent(ProductCard).vm.$emit('edit', leanProduct)
    await flushPromises()

    expect(fetchProductById).toHaveBeenCalledWith('prod-1')
    const form = wrapper.findComponent(ProductForm)
    expect(form.props('product')).toEqual(leanProduct)
    expect(showToast).toHaveBeenCalled()
  })
})
