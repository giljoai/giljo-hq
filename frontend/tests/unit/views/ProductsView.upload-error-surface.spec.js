/**
 * SEC-0001 Phase 2 — ProductsView upload error surfacing.
 *
 * Mounts ProductsView and asserts the uploader's catch branch surfaces
 * the backend-supplied detail string when the vision-document endpoint
 * returns 415 UPLOAD_TYPE_NOT_ALLOWED. The view normally calls
 * `api.visionDocuments.upload(formData)`; we override that mock per-test
 * to reject with an axios-shaped error.
 *
 * The view calls `showToast({ message, type, timeout })` from
 * `@/composables/useToast`, which is mocked globally in setup.js. We
 * replace that mock here so we can assert the exact message text.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { nextTick } from 'vue'

// Capture showToast calls via a spy shared with the useToast mock.
const showToastSpy = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastSpy }),
}))

// Pull the mocked api (declared globally in tests/setup.js) so we can
// tweak `visionDocuments.upload` per-test.
import { api } from '@/services/api'

// Stubs for heavy child components — we only care about the uploader path.
vi.mock('@/components/products/ActivationWarningDialog.vue', () => ({ default: { template: '<div class="stub-activation-warning" />' } }))
vi.mock('@/components/products/ProductDeleteDialog.vue', () => ({ default: { template: '<div class="stub-delete-dialog" />' } }))
vi.mock('@/components/products/ProductDetailsDialog.vue', () => ({ default: { template: '<div class="stub-details-dialog" />' } }))
vi.mock('@/components/products/ProductTuningDialog.vue', () => ({ default: { template: '<div class="stub-tuning-dialog" />' } }))
vi.mock('@/components/products/DeletedProductsRecoveryDialog.vue', () => ({ default: { template: '<div class="stub-recovery-dialog" />' } }))
vi.mock('@/components/products/ProductForm.vue', () => ({ default: { template: '<div class="stub-product-form" />' } }))

// Avoid unnecessary initial API side effects from composables.
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

import { createRouter, createMemoryHistory } from 'vue-router'
import ProductsView from '@/views/ProductsView.vue'

// FE-9427: ProductsView calls useRoute() and useRouter() -- onMounted reads
// ?create / ?tune and then router.replace()s them off the URL. Both returned
// `undefined` without a router installed, so that deep-link path was inert.
const productsRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/products', name: 'Products', component: { template: '<div />' } },
  ],
})

function makeAxiosError(status, body) {
  // Shape matches axios error objects.
  const err = new Error(`HTTP ${status}`)
  err.response = { status, data: body }
  return err
}

function makeFile(name, sizeBytes) {
  const blob = new Blob([new Uint8Array(sizeBytes)], { type: 'text/plain' })
  return new File([blob], name, { type: 'text/plain' })
}

describe('ProductsView — SEC-0001 upload error surfacing', () => {
  let wrapper

  beforeEach(() => {
    showToastSpy.mockClear()
    // Default — products.create succeeds so the uploader can reach the
    // axios call. Tests that need it failing override this.
    api.products.create.mockResolvedValue({ data: { id: 'product-xyz', name: 'Demo' } })
  })

  async function mountView() {
    wrapper = mount(ProductsView, {
      global: {
        plugins: [createTestingPinia({ createSpy: vi.fn, stubActions: false }), productsRouter],
        stubs: {
          'v-container': { template: '<div><slot /></div>' },
          'v-card': { template: '<div><slot /></div>' },
          'v-btn': { template: '<button><slot /></button>' },
        },
      },
    })
    await flushPromises()
    return wrapper
  }

  it('surfaces backend UPLOAD_TYPE_NOT_ALLOWED detail via toast on 415', async () => {
    // Arrange — backend structured 415 response.
    api.visionDocuments.upload.mockRejectedValueOnce(
      makeAxiosError(415, {
        error_code: 'UPLOAD_TYPE_NOT_ALLOWED',
        message: 'Only .txt, .md, and .markdown files are accepted.',
        context: { filename: 'evil.pdf', extension: '.pdf' },
      }),
    )

    await mountView()

    // Act — invoke the uploader directly with a valid-looking file so the
    // client pre-check passes and the axios call actually fires.
    await wrapper.vm.uploadVisionFilesOnAttach({
      productName: 'Demo',
      files: [makeFile('mission.txt', 1024)],
    })
    await flushPromises()
    await nextTick()

    // Assert — toast carries backend detail, NOT a generic "Upload failed".
    const errorCall = showToastSpy.mock.calls.find(([opts]) => opts?.type === 'error')
    expect(errorCall).toBeTruthy()
    expect(errorCall[0].message).toContain('Only .txt, .md, and .markdown files are accepted.')
    expect(errorCall[0].message).toContain('mission.txt')
  })

  it('surfaces backend UPLOAD_TOO_LARGE detail via toast on 413 (dict-detail shape)', async () => {
    // Backend using bare HTTPException(detail={...}) produces this shape
    // (FastAPI wraps dict details under `detail`). Frontend must unwrap.
    api.visionDocuments.upload.mockRejectedValueOnce(
      makeAxiosError(413, {
        detail: {
          error_code: 'UPLOAD_TOO_LARGE',
          message: 'File is too large. Maximum size is 5 MB.',
          context: { max_bytes: 5242880 },
        },
      }),
    )

    await mountView()

    await wrapper.vm.uploadVisionFilesOnAttach({
      productName: 'Demo',
      files: [makeFile('ok.txt', 1024)],
    })
    await flushPromises()
    await nextTick()

    const errorCall = showToastSpy.mock.calls.find(([opts]) => opts?.type === 'error')
    expect(errorCall).toBeTruthy()
    expect(errorCall[0].message).toContain('File is too large. Maximum size is 5 MB.')
  })

  it('rejects an oversize file in the client pre-check WITHOUT firing the axios POST', async () => {
    await mountView()

    await wrapper.vm.uploadVisionFilesOnAttach({
      productName: 'Demo',
      files: [makeFile('big.txt', 6 * 1024 * 1024)],
    })
    await flushPromises()

    // No network call should have been attempted.
    expect(api.visionDocuments.upload).not.toHaveBeenCalled()
    // Client-side error toast visible instead.
    const errorCall = showToastSpy.mock.calls.find(([opts]) => opts?.type === 'error')
    expect(errorCall).toBeTruthy()
    expect(errorCall[0].message).toMatch(/5\s?MB/)
    expect(errorCall[0].message).toContain('big.txt')
  })

  it('rejects a disallowed extension in the client pre-check', async () => {
    await mountView()

    await wrapper.vm.uploadVisionFilesOnAttach({
      productName: 'Demo',
      files: [makeFile('evil.pdf', 1024)],
    })
    await flushPromises()

    expect(api.visionDocuments.upload).not.toHaveBeenCalled()
    const errorCall = showToastSpy.mock.calls.find(([opts]) => opts?.type === 'error')
    expect(errorCall).toBeTruthy()
    expect(errorCall[0].message).toMatch(/\.txt.*\.md/i)
  })
})
