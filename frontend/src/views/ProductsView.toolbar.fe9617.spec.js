import { describe, it, expect, beforeEach, vi } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  route: { path: '/Products', query: {} },
  deleted: [],
  showDeletedDialog: null,
}))

vi.mock('vue-router', () => ({
  useRoute: () => h.route,
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

vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({ fetchFieldToggleConfig: vi.fn(() => Promise.resolve()) }),
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

vi.mock('@/composables/useProductActivation', () => ({
  useProductActivation: () => ({ toggleProductActivation: vi.fn() }),
}))

vi.mock('@/composables/useProductSoftDelete', async () => {
  const { ref } = await import('vue')
  return {
    useProductSoftDelete: () => {
      h.showDeletedDialog = ref(false)
      return {
        showDeletedProductsDialog: h.showDeletedDialog,
        deletedProducts: ref(h.deleted),
        restoringProductId: ref(null),
        purgingProductId: ref(null),
        purgingAllProducts: ref(false),
        loadDeletedProducts: vi.fn(() => Promise.resolve()),
        restoreProduct: vi.fn(),
        purgeDeletedProduct: vi.fn(),
        purgeAllDeletedProducts: vi.fn(),
      }
    },
  }
})

vi.mock('@/services/api', () => ({ default: {} }))

import ProductsView from './ProductsView.vue'
import ProductForm from '@/components/products/ProductForm.vue'

async function mountView() {
  const wrapper = shallowMount(ProductsView)
  await flushPromises()
  return wrapper
}

describe('ProductsView toolbar — icon buttons (FE-9617)', () => {
  beforeEach(() => {
    h.route = { path: '/Products', query: {} }
    h.deleted = []
  })

  it('the add control is a bare + icon with a tooltip, not a labelled button', async () => {
    const w = await mountView()
    const add = w.find('[data-testid="products-new"]')

    expect(add.exists()).toBe(true)
    expect(add.attributes('icon')).toBe('mdi-plus')
    expect(add.attributes('title')).toBe('New product')
    expect(add.attributes('aria-label')).toBe('New product')
    expect(add.text()).not.toContain('New Product')
  })

  it('clicking the + still opens the new-product dialog', async () => {
    const w = await mountView()
    expect(w.findComponent(ProductForm).props('modelValue')).toBe(false)
    await w.find('[data-testid="products-new"]').trigger('click')
    expect(w.findComponent(ProductForm).props('modelValue')).toBe(true)
  })

  it('the deleted-products control is the restore icon, disabled and grey at zero', async () => {
    const w = await mountView()
    const btn = w.find('[data-testid="products-deleted-open"]')

    expect(btn.attributes('icon')).toBe('mdi-delete-restore')
    expect(btn.attributes('color')).toBe('grey')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.attributes('title')).toBe('Deleted products (0)')
    expect(btn.text()).not.toContain('Deleted')
  })

  it('the badge is hidden at zero and shows the count above zero, in warning colour', async () => {
    const empty = await mountView()
    expect(empty.find('[data-testid="products-deleted-open"]').attributes('color')).toBe('grey')
    const badgeOff = empty.find('[data-testid="products-deleted-badge"]')
    expect(badgeOff.attributes('model-value')).toBe('false')

    h.deleted = [{ id: 'p1' }, { id: 'p2' }, { id: 'p3' }]
    const w = await mountView()
    const badge = w.find('[data-testid="products-deleted-badge"]')
    expect(badge.attributes('model-value')).toBe('true')
    expect(badge.attributes('content')).toBe('3')
    expect(badge.attributes('color')).toBe('warning')

    const btn = w.find('[data-testid="products-deleted-open"]')
    expect(btn.attributes('color')).toBe('warning')
    expect(btn.attributes('disabled')).toBeUndefined()
    expect(btn.attributes('title')).toBe('Deleted products (3)')
  })

  it('clicking the restore icon still opens the deleted-products dialog', async () => {
    h.deleted = [{ id: 'p1' }]
    const w = await mountView()
    await w.find('[data-testid="products-deleted-open"]').trigger('click')
    expect(h.showDeletedDialog.value).toBe(true)
  })
})
