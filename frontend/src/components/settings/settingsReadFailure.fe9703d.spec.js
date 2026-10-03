import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

const h = vi.hoisted(() => ({ showToast: vi.fn(), settingsGet: vi.fn(), fetchFieldToggle: vi.fn() }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.showToast }) }))
vi.mock('@/services/api', () => ({
  default: {
    settings: { get: h.settingsGet },
    users: { getFieldToggleConfig: h.fetchFieldToggle },
    visionDocuments: { listByProduct: vi.fn() },
  },
}))
vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn().mockResolvedValue({}), getGiljoMode: () => 'ce', getEdition: () => 'community' },
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/Products', query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: [],
    activeProduct: null,
    currentProductId: null,
    fetchProducts: vi.fn(() => Promise.resolve()),
    fetchActiveProduct: vi.fn(() => Promise.resolve(true)),
    fetchProductById: vi.fn(() => Promise.resolve(null)),
    setDefaultProduct: vi.fn(() => Promise.resolve(null)),
  }),
}))
vi.mock('@/composables/useProductVisionUpload', async () => {
  const { ref } = await import('vue')
  return {
    useProductVisionUpload: () => ({
      uploadingVision: ref(false), uploadProgress: ref(0), visionUploadError: ref(null),
      existingVisionDocuments: ref([]), loadExistingVisionDocuments: vi.fn(),
      uploadVisionFilesOnAttach: vi.fn(), resetUploadState: vi.fn(),
    }),
  }
})
vi.mock('@/composables/useProductActivation', () => ({ useProductActivation: () => ({ toggleProductActivation: vi.fn() }) }))
vi.mock('@/composables/useProductSoftDelete', async () => {
  const { ref } = await import('vue')
  return {
    useProductSoftDelete: () => ({
      showDeletedProductsDialog: ref(false), deletedProducts: ref([]), restoringProductId: ref(null),
      purgingProductId: ref(null), purgingAllProducts: ref(false), loadDeletedProducts: vi.fn(() => Promise.resolve()),
      restoreProduct: vi.fn(), purgeDeletedProduct: vi.fn(), purgeAllDeletedProducts: vi.fn(),
    }),
  }
})

import ToastPreferencesCard from '@/components/settings/ToastPreferencesCard.vue'
import ProductsView from '@/views/ProductsView.vue'

const failure = (message) =>
  Object.assign(new Error('x'), { isAxiosError: true, response: { status: 500, data: { message } } })

describe('settings reads that fail are shown', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    localStorage.removeItem('giljo_settings')
  })

  it('toast preferences: a failed server read is shown and the local-only Save still works', async () => {
    h.settingsGet.mockRejectedValue(failure('preferences unavailable'))
    const wrapper = mount(ToastPreferencesCard)
    await flushPromises()

    const err = wrapper.find('[data-test="notification-settings-error"]')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('preferences unavailable')
    expect(wrapper.find('[data-test="save-notification-btn"]').attributes('disabled')).toBeUndefined()
  })

  it('products: a failed field-toggle read is a toast', async () => {
    h.fetchFieldToggle.mockRejectedValue(failure('field toggles unavailable'))
    shallowMount(ProductsView)
    await flushPromises()

    expect(h.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('field toggles unavailable') }),
    )
  })
})
