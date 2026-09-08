/**
 * ProductsView.editProduct.spec.js — BE-6066 P4
 *
 * After P4 the products LIST object is LEAN (no tech_stack / architecture /
 * test_config). So opening Edit (or Details) must fetch the FULL product so
 * ProductForm / ProductDetailsDialog receive the detail fields they edit/render.
 *
 * Verifies: clicking Edit on a card fetches the full product (mocked api via the
 * store) and ProductForm receives THAT full object, not the lean list row.
 *
 * Edition scope: CE
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

// vi.mock factories are hoisted above the module body (and above ES imports),
// so EVERYTHING they reference must live in a vi.hoisted block too.
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
    // NOTE: deliberately NO tech_stack / architecture / test_config (lean list).
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
// FE-9419: these three return REAL refs, matching both the real composables
// and the sibling ProductsView.spec.js. A plain `{ value: x }` stand-in is not
// a ref, so Vue's template auto-unwrap (which tests isRef) leaves it alone and
// ProductsView hands the wrapper OBJECT to every child prop derived from it —
// `:model-value="showDeletedProductsDialog"` arrives as an object, not a
// boolean. That produced eleven invalid-prop warnings and, worse, meant any
// assertion about those children was reading a state the component never has.
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

// FE-9427: ProductsView calls useRoute() and useRouter() -- onMounted reads
// ?create / ?tune and then router.replace()s them off the URL. Both returned
// `undefined` without a router installed, so that whole deep-link path was
// inert and the view's own optional chaining was the only thing hiding it.
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
    await flushPromises() // let onMounted/loadProducts resolve so loading=false

    const card = wrapper.findComponent(ProductCard)
    expect(card.exists()).toBe(true)

    // Click Edit on the lean card row.
    card.vm.$emit('edit', leanProduct)
    await flushPromises()

    // It fetched the FULL product by id...
    expect(fetchProductById).toHaveBeenCalledWith('prod-1')

    // ...and ProductForm received the full object (with detail relations).
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
