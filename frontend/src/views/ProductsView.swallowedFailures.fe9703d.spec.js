import { describe, it, expect, beforeEach, vi } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

const h = vi.hoisted(() => ({
  showToast: vi.fn(),
  deleteProduct: vi.fn(),
  fetchProductById: vi.fn(),
  listByProduct: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/Products', query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: [{ id: 'prod-1', name: 'Acme' }],
    activeProduct: null,
    currentProductId: null,
    fetchProducts: vi.fn(() => Promise.resolve()),
    fetchActiveProduct: vi.fn(() => Promise.resolve(true)),
    fetchProductById: h.fetchProductById,
    setDefaultProduct: vi.fn(() => Promise.resolve(null)),
    deleteProduct: h.deleteProduct,
  }),
}))
vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({ fetchFieldToggleConfig: vi.fn(() => Promise.resolve()) }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.showToast }) }))
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
      loadDeletedProducts: vi.fn(() => Promise.resolve()),
      restoreProduct: vi.fn(),
      purgeDeletedProduct: vi.fn(),
      purgeAllDeletedProducts: vi.fn(),
    }),
  }
})
vi.mock('@/services/api', () => ({ default: { visionDocuments: { listByProduct: h.listByProduct } } }))

import ProductsView from './ProductsView.vue'
import { createStatusesStore } from '@/stores/createStatusesStore'

const failure = (status, message) =>
  Object.assign(new Error('x'), { isAxiosError: true, response: { status, data: { message } } })
const errorToastMentioning = (text) =>
  h.showToast.mock.calls.some(([o]) => o.type === 'error' && String(o.message).includes(text))

describe('ProductsView: swallowed failures are shown', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    h.fetchProductById.mockResolvedValue(null)
    h.deleteProduct.mockResolvedValue(undefined)
    h.listByProduct.mockResolvedValue({ data: [] })
  })

  it('a failed vision-list refresh is a toast', async () => {
    h.listByProduct.mockRejectedValueOnce(failure(500, 'vision list unavailable'))
    const wrapper = shallowMount(ProductsView)
    await flushPromises()
    wrapper.vm.selectedProduct = { id: 'prod-1', name: 'Acme' }

    await wrapper.vm.handleProductRefresh()
    await flushPromises()

    expect(errorToastMentioning('vision list unavailable')).toBe(true)
  })

  it('a failed cleanup of the auto-saved product is a toast, a 404 is silent', async () => {
    const wrapper = shallowMount(ProductsView)
    await flushPromises()

    wrapper.vm.autoSavedForAnalysis = 'prod-auto'
    h.deleteProduct.mockRejectedValueOnce(failure(500, 'cleanup refused'))
    await wrapper.vm.closeDialog()
    await flushPromises()
    expect(errorToastMentioning('cleanup refused')).toBe(true)

    h.showToast.mockClear()
    wrapper.vm.autoSavedForAnalysis = 'prod-auto'
    h.deleteProduct.mockRejectedValueOnce(failure(404, 'gone'))
    await wrapper.vm.closeDialog()
    await flushPromises()
    expect(h.showToast).not.toHaveBeenCalled()
  })
})

describe('createStatusesStore: a malformed payload', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('rejects and leaves the cache unloaded so the next call retries', async () => {
    const fetchStatuses = vi.fn().mockResolvedValue({ data: { not: 'a list' } })
    const useStore = createStatusesStore('malformedStatuses', fetchStatuses)
    const store = useStore()

    await expect(store.ensureLoaded()).rejects.toThrow()
    expect(store.loaded).toBe(false)

    fetchStatuses.mockResolvedValueOnce({ data: [{ value: 'active', label: 'Active' }] })
    await store.ensureLoaded()
    expect(fetchStatuses).toHaveBeenCalledTimes(2)
    expect(store.loaded).toBe(true)
  })
})
