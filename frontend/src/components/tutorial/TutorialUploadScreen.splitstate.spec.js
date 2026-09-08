/**
 * TutorialUploadScreen.splitstate.spec.js
 *
 * THE DEFECT: with at least one product already owned, an ordinary click on the
 * Tools page's "Learning" card re-enters the onboarding tour, and the upload beat
 * then HALF-lands -- both halves at once, a product existing server-side named
 * after the uploaded file while the tour still sits on "Attach your vision
 * document" as though nothing had happened. Two bad outcomes from one action: a
 * stranded product nobody asked for, and a tour that looks broken.
 *
 * THE MECHANISM. `handleFiles` does:
 *
 *     await uploadVisionFilesOnAttach({ productName, files })
 *     const productId = editingProduct.value?.id
 *     if (!productId) return              // <-- strands here
 *     ...
 *     analysisStarted.value = true        // <-- never reached
 *
 * and inside the composable's create branch:
 *
 *     const product = await productStore.createProduct({ name: productName })
 *     editingProduct.value = product
 *     autoSavedForAnalysis.value = product.id
 *
 * `createProduct` returns `response.data`, and its call is written
 * `(await api.products?.create(...)) || { data: null }` -- so a response
 * carrying no usable body is a NORMAL outcome there, not an error. When that
 * happens the product has already been created server-side, but `product` is
 * null: `editingProduct.value` is set to null, `product.id` throws, the
 * composable's own catch swallows it into a generic toast, and `handleFiles`
 * then early-returns on the falsy id. Server state advanced; UI state did not.
 *
 * WHAT THIS SUITE ASSERTS IS THE INVARIANT, NOT THE TRIGGER. The trigger could
 * be any future way the client fails to bind a product it just caused to exist
 * -- a shape change, a proxy, a partial failure. What must never happen is the
 * two halves diverging in silence: if the upload got far enough to create a
 * product, the screen must not sit on the drop zone as though it had not. A
 * test pinned to one trigger would pass the day the trigger changed and the
 * defect returned.
 *
 * MUSEUM RULE: written to FAIL on current code before any behaviour changes.
 *
 * Edition Scope: Both (shared frontend/src; both editions render this screen).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  editingRef: null,
  /** Simulates the composable: the server created a product, the client got no row. */
  uploadImpl: null,
  stageAnalysis: vi.fn(),
  createdServerSide: false,
  visionUploadError: null,
  visionUploadRetrySafe: null,
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => null),
  }),
}))

// The mock mirrors the REAL return shape, `visionUploadError` included. My
// first version omitted it, and the component's read of `.value` on an
// undefined ref threw inside the drop handler -- so the suite failed for the
// mock's shape rather than for the behaviour under test. Same
// mock-does-not-match-the-contract trap this codebase has been collecting;
// worth stating because a mock is a contract you are choosing to trust.
vi.mock('@/composables/useProductVisionUpload', () => ({
  useProductVisionUpload: ({ editingProduct }) => {
    h.editingRef = editingProduct
    h.visionUploadError = ref(null)
    // FE-9553c added this ref to the composable. Missing it here made the
    // component's `visionUploadRetrySafe.value` read throw an UNHANDLED error
    // -- which vitest fails the run on even though every test still passed.
    h.visionUploadRetrySafe = ref(null)
    return {
      uploadingVision: ref(false),
      visionUploadError: h.visionUploadError,
      visionUploadRetrySafe: h.visionUploadRetrySafe,
      uploadVisionFilesOnAttach: vi.fn(async (args) => h.uploadImpl?.(args)),
    }
  },
}))

vi.mock('@/composables/useVisionAnalysis', () => ({
  useVisionAnalysis: () => ({
    analysisPromptText: ref(''),
    promptFallbackText: ref(''),
    analysisHintVisible: ref(false),
    stageAnalysis: (...a) => h.stageAnalysis(...a),
    onVisionAnalysisComplete: vi.fn(),
    resetAnalysisState: vi.fn(),
  }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(async () => true) }),
}))

import TutorialUploadScreen from './TutorialUploadScreen.vue'

function mountScreen(productId = null) {
  return mount(TutorialUploadScreen, {
    props: { productId },
    global: { stubs: { 'v-icon': true, 'v-btn': true } },
  })
}

async function dropFile(wrapper, name = 'sample-vision.md') {
  const file = new File(['vision body'], name, { type: 'text/markdown' })
  await wrapper
    .find('[data-testid="tutorial-drop-zone"]')
    .trigger('drop', { dataTransfer: { files: [file] } })
  await flushPromises()
}

/** Is the screen still showing the drop zone, i.e. did the beat not advance? */
function stillOnDropZone(wrapper) {
  return wrapper.find('[data-testid="tutorial-drop-zone"]').exists()
}

describe('TutorialUploadScreen — the upload beat must not half-land', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.editingRef = null
    h.uploadImpl = null
    h.createdServerSide = false
  })

  it('advances when the upload binds the product it created (control)', async () => {
    // The happy path, asserted first so the failures below are attributable to
    // the split state rather than to a screen that never advances at all.
    h.uploadImpl = () => {
      h.createdServerSide = true
      h.editingRef.value = { id: 'prod-new', name: 'sample-vision' }
    }
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    expect(h.createdServerSide).toBe(true)
    expect(h.stageAnalysis).toHaveBeenCalled()
    expect(stillOnDropZone(wrapper)).toBe(false)
  })

  it('does NOT strand the operator when a product was created but no row came back', async () => {
    // The reported defect. The composable's create branch assigns whatever
    // createProduct returned -- null is a normal outcome of that call -- and
    // the product exists server-side regardless.
    //
    // MY FIRST VERSION OF THIS ASSERTION WAS WRONG and demanded the wrong
    // remedy: it required the beat to ADVANCE off the drop zone. Advancing
    // would show the analysis panel, which says "Your document is uploaded" and
    // offers a prompt for an analysis that is not running -- trading a silent
    // failure for a confident false one. The requirement is that the operator
    // is not left WITHOUT INFORMATION; it is not that the tour proceeds. So the
    // assertion is now on the failure being visible, which is the honest
    // remedy, and the beat deliberately stays put.
    h.uploadImpl = () => {
      h.createdServerSide = true
      h.editingRef.value = null
      h.visionUploadError.value =
        'A product was created but the file could not be attached to it. Open Products to see it, or try again from there.'
      // Something WAS created, so a retry would mint a second one.
      h.visionUploadRetrySafe.value = false
    }
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    // A product now exists that the operator did not ask for by name...
    expect(h.createdServerSide).toBe(true)
    // ...so the screen must not sit here as though nothing happened.
    expect(wrapper.find('[data-testid="tutorial-upload-failure"]').exists()).toBe(true)
    // And it must name the possibility that a product WAS created, because
    // retrying blindly would then mint a second one.
    expect(wrapper.find('[data-testid="tutorial-upload-failure"]').text()).toMatch(/product/i)
    // Still on the drop zone ON PURPOSE: this is where a retry lives, and the
    // analysis panel would assert an analysis that is not running.
    expect(stillOnDropZone(wrapper)).toBe(true)
  })

  it('surfaces something to the operator rather than failing silently', async () => {
    // The weaker half of the same claim, kept separate so a fix that advances
    // the beat and one that explains the failure are both admissible -- this
    // suite pins that SOMETHING is communicated, not which remedy is chosen.
    h.uploadImpl = () => {
      h.createdServerSide = true
      h.editingRef.value = null
      h.visionUploadError.value =
        'A product was created but the file could not be attached to it. Open Products to see it, or try again from there.'
      // Something WAS created, so a retry would mint a second one.
      h.visionUploadRetrySafe.value = false
    }
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    const text = wrapper.text()
    const saysSomething = /again|problem|could not|couldn't|failed|retry/i.test(text)
    expect(saysSomething || !stillOnDropZone(wrapper)).toBe(true)
  })
})
