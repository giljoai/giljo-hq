/**
 * BE-9356 follow-up — the delete dialog must never show one product's counts
 * under another product's name.
 *
 * `confirmDelete` opens the dialog FIRST and fetches the cascade impact after,
 * and `cascadeImpact` was only ever cleared by `cancelDelete`. Neither the
 * successful-delete path nor the non-404 error branch reset it, so a second
 * delete whose impact fetch failed rendered the PREVIOUS product's counts
 * beneath the new product's name on a destructive confirmation.
 *
 * This was harmless while the template read field names the backend never sent
 * (it always painted blanks). Correcting those names is what turned it into
 * confident misinformation, so the fix belongs with them.
 *
 * The dialog is mounted for real -- only `v-dialog` is stubbed to render its
 * slot, so the assertions run against the component's real template.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'

const showToastSpy = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastSpy }),
}))

import { api } from '@/services/api'

// Heavy siblings stubbed -- ProductDeleteDialog is deliberately NOT, because it
// is the component whose rendered output this spec is about.
vi.mock('@/components/products/ActivationWarningDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/products/ProductDetailsDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/products/ProductTuningDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/products/DeletedProductsRecoveryDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/products/ProductForm.vue', () => ({ default: { template: '<div />' } }))

vi.mock('@/composables/useProductActivation', () => ({
  useProductActivation: () => ({
    showActivationWarning: { value: false },
    pendingActivation: { value: null },
    currentActiveProduct: { value: null },
    toggleProductActivation: vi.fn(),
    confirmActivation: vi.fn(),
    cancelActivation: vi.fn(),
  }),
}))
vi.mock('@/composables/useProductSoftDelete', () => ({
  useProductSoftDelete: () => ({
    showDeletedProductsDialog: { value: false },
    deletedProducts: { value: [] },
    restoringProductId: { value: null },
    purgingProductId: { value: null },
    purgingAllProducts: { value: false },
    loadDeletedProducts: vi.fn(() => Promise.resolve()),
    restoreProduct: vi.fn(() => Promise.resolve()),
    purgeDeletedProduct: vi.fn(() => Promise.resolve()),
    purgeAllDeletedProducts: vi.fn(() => Promise.resolve()),
  }),
}))

import ProductsView from '@/views/ProductsView.vue'

// Distinctive values so a match cannot come from unrelated chrome (page counts,
// the literal "10 days", ids).
const PRODUCT_A_IMPACT = { total_projects: 47, total_tasks: 88, total_vision_documents: 61 }
const STALE_VALUES = Object.values(PRODUCT_A_IMPACT).map(String)

const makeAxiosError = (status) => {
  const err = new Error(`HTTP ${status}`)
  err.response = { status, data: { detail: 'boom' } }
  return err
}

describe('ProductsView — stale cascade impact between two deletes', () => {
  let wrapper

  beforeEach(() => {
    showToastSpy.mockClear()
    api.products.getCascadeImpact.mockReset()
  })

  async function mountView() {
    wrapper = mount(ProductsView, {
      global: {
        plugins: [createTestingPinia({ createSpy: vi.fn, stubActions: false })],
        stubs: {
          'v-container': { template: '<div><slot /></div>' },
          'v-dialog': { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()
    return wrapper
  }

  /** Open the delete dialog for A, with its impact fetch succeeding. */
  async function openDeleteForProductA() {
    api.products.getCascadeImpact.mockResolvedValueOnce({ data: PRODUCT_A_IMPACT })
    await wrapper.vm.confirmDelete({ id: 'product-a', name: 'Product Alpha' })
    await flushPromises()
  }

  it("does not render product A's counts when product B's impact fetch 500s", async () => {
    await mountView()
    await openDeleteForProductA()

    // Sanity: A's impact really is on screen, so a later absence means cleared.
    for (const value of STALE_VALUES) {
      expect(wrapper.text(), `setup failed: ${value} never rendered for A`).toContain(value)
    }

    // A's delete succeeds and closes the dialog (deletingProduct nulled,
    // cascadeImpact left holding A). The user now deletes B and the impact
    // fetch fails with a non-404.
    api.products.getCascadeImpact.mockRejectedValueOnce(makeAxiosError(500))
    await wrapper.vm.confirmDelete({ id: 'product-b', name: 'Product Beta' })
    await flushPromises()

    // We are genuinely showing B's dialog -- not merely a closed one.
    expect(wrapper.text()).toContain('Product Beta')

    for (const value of STALE_VALUES) {
      expect(wrapper.text(), `stale count ${value} from Product Alpha still rendered`).not.toContain(
        value
      )
    }
    expect(wrapper.text()).not.toContain('Kept with this product in the trash')
  })

  it('also clears when the request dies with no response at all', async () => {
    // A dropped connection leaves error.response undefined, so the 404 check
    // short-circuits to the same non-clearing else branch.
    await mountView()
    await openDeleteForProductA()

    api.products.getCascadeImpact.mockRejectedValueOnce(new Error('Network Error'))
    await wrapper.vm.confirmDelete({ id: 'product-b', name: 'Product Beta' })
    await flushPromises()

    for (const value of STALE_VALUES) {
      expect(wrapper.text(), `stale count ${value} survived a network failure`).not.toContain(value)
    }
  })
})
