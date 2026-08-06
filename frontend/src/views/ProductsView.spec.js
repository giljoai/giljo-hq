/**
 * ProductsView.spec.js — FE-9222
 *
 * The context-tuning banner deep-links here with ?tune=<product_id>. On mount,
 * after the product list loads, the matching product's ProductTuningDialog opens
 * and the query param is stripped. An unknown/missing id fails soft (no dialog,
 * param still stripped) — the same strip-after-acting idiom as ?create=true.
 *
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  route: { path: '/Products', query: {} },
  products: [],
  fetchProducts: vi.fn(() => Promise.resolve()),
  fetchFieldToggle: vi.fn(() => Promise.resolve()),
  loadDeleted: vi.fn(() => Promise.resolve()),
}))

vi.mock('vue-router', () => ({
  useRoute: () => h.route,
  useRouter: () => ({ push: h.push, replace: h.replace }),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: h.products,
    activeProduct: null,
    currentProductId: null,
    fetchProducts: h.fetchProducts,
    fetchProductById: vi.fn(() => Promise.resolve(null)),
  }),
}))

vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({ fetchFieldToggleConfig: h.fetchFieldToggle }),
}))

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

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

vi.mock('@/composables/useProductActivation', async () => {
  const { ref } = await import('vue')
  return {
    useProductActivation: () => ({
      showActivationWarning: ref(false),
      pendingActivation: ref(null),
      currentActiveProduct: ref(null),
      toggleProductActivation: vi.fn(),
      confirmActivation: vi.fn(),
      cancelActivation: vi.fn(),
    }),
  }
})

vi.mock('@/composables/useProductSoftDelete', async () => {
  const { ref } = await import('vue')
  return {
    useProductSoftDelete: () => ({
      showDeletedProductsDialog: ref(false),
      deletedProducts: ref([]),
      restoringProductId: ref(null),
      purgingProductId: ref(null),
      purgingAllProducts: ref(false),
      loadDeletedProducts: h.loadDeleted,
      restoreProduct: vi.fn(),
      purgeDeletedProduct: vi.fn(),
      purgeAllDeletedProducts: vi.fn(),
    }),
  }
})

vi.mock('@/services/api', () => ({ default: {} }))

import ProductsView from './ProductsView.vue'
import ProductTuningDialog from '@/components/products/ProductTuningDialog.vue'

async function mountView() {
  const wrapper = shallowMount(ProductsView)
  await flushPromises()
  return wrapper
}

describe('ProductsView — FE-9222 ?tune deep-link', () => {
  beforeEach(() => {
    h.push.mockClear()
    h.replace.mockClear()
    h.route = { path: '/Products', query: {} }
    h.products = [
      { id: 'prod-1', name: 'Acme' },
      { id: 'prod-2', name: 'Beta' },
    ]
  })

  it('opens the tuning dialog for the product named by ?tune and strips the param', async () => {
    h.route.query = { tune: 'prod-2' }
    const wrapper = await mountView()

    const dialog = wrapper.findComponent(ProductTuningDialog)
    expect(dialog.props('modelValue')).toBe(true)
    expect(dialog.props('product')).toEqual({ id: 'prod-2', name: 'Beta' })
    expect(h.replace).toHaveBeenCalledWith({ path: '/Products' })
  })

  it('fails soft on an unknown product id — no dialog, param still stripped', async () => {
    h.route.query = { tune: 'ghost-id' }
    const wrapper = await mountView()

    const dialog = wrapper.findComponent(ProductTuningDialog)
    expect(dialog.props('modelValue')).toBe(false)
    expect(dialog.props('product')).toBe(null)
    expect(h.replace).toHaveBeenCalledWith({ path: '/Products' })
  })

  it('does nothing when no ?tune param is present', async () => {
    const wrapper = await mountView()

    const dialog = wrapper.findComponent(ProductTuningDialog)
    expect(dialog.props('modelValue')).toBe(false)
    expect(h.replace).not.toHaveBeenCalled()
  })
})
