/**
 * TutorialUploadScreen.retry.spec.js — FE-9553c
 *
 * THE SIBLING CASE. #1040 covered the upload whose product was CREATED but
 * could not be bound (a 2xx carrying no usable body). This is the upload whose
 * product was never created at all -- a wire trace caught a
 * `POST /api/v1/products/` returning 429 -- which lands on the same
 * `if (!productId) return` and leaves the beat unable to proceed.
 *
 * The two must not be told to the operator the same way, and that is the whole
 * point of this suite rather than a nicety:
 *
 *   - NOTHING WAS CREATED  -> retrying is clean. Press the button again.
 *   - SOMETHING WAS CREATED but unbound -> retrying mints a SECOND product.
 *
 * A single "something went wrong, try again" covering both would actively
 * mislead in the second case, which is how an operator ends up with three
 * products named after the same file.
 *
 * WHAT DOOR D ALREADY DOES, and why this is a CLASS fix rather than a local
 * one: FE-9566 gave the prompt beat `tutorial-prompt-error` +
 * `tutorial-prompt-retry` + a manual escape for exactly this failure. Doors A
 * and B never got it. Matching that shape here means the tour behaves the same
 * way whichever door the operator walked in through, instead of one beat
 * explaining itself and its sibling going quiet.
 *
 * PREMISE CHECK FIRST. The work order described this beat as having "NO
 * error/retry surface at all". #1040 gave it an error surface, so the first
 * test below probes what actually renders today rather than assuming, and the
 * suite is scoped to what is genuinely missing: a retry, a manual escape, and
 * a message that distinguishes the two failure kinds.
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
  visionUploadError: null,
  visionUploadRetrySafe: null,
  /** Simulates the composable's outcome for this attempt. */
  uploadImpl: null,
  uploadCalls: 0,
  stageAnalysis: vi.fn(),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => null),
  }),
}))

// Mirrors the REAL return shape, visionUploadError AND visionUploadRetrySafe
// included. This is the third time in this lane that a mock missing a key the
// real composable returns produced a red that was about the mock rather than
// the code -- so the rule earned here is: when you ADD a ref to a composable,
// grep its mocks in the same edit. The suite cannot see a contract it did not
// copy.
vi.mock('@/composables/useProductVisionUpload', () => ({
  useProductVisionUpload: ({ editingProduct }) => {
    h.editingRef = editingProduct
    h.visionUploadError = ref(null)
    h.visionUploadRetrySafe = ref(null)
    return {
      uploadingVision: ref(false),
      visionUploadError: h.visionUploadError,
      visionUploadRetrySafe: h.visionUploadRetrySafe,
      uploadVisionFilesOnAttach: vi.fn(async (args) => {
        h.uploadCalls += 1
        return h.uploadImpl?.(args)
      }),
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
    global: { stubs: { 'v-icon': true } },
  })
}

async function dropFile(wrapper, name = 'sample-vision.md') {
  const file = new File(['vision body'], name, { type: 'text/markdown' })
  await wrapper
    .find('[data-testid="tutorial-drop-zone"]')
    .trigger('drop', { dataTransfer: { files: [file] } })
  await flushPromises()
}

/** The create never happened: no product, and the composable says so. */
function createFailedOutright(message = 'Too many requests. Wait a moment and try again.') {
  return () => {
    h.editingRef.value = null
    h.visionUploadError.value = message
    h.visionUploadRetrySafe.value = true // nothing was created
  }
}

/** The create landed server-side but produced no usable row (the #1040 case). */
function createdButUnbound() {
  return () => {
    h.editingRef.value = null
    h.visionUploadError.value =
      'A product was created but the file could not be attached to it. Open Products to see it, or try again from there.'
    h.visionUploadRetrySafe.value = false // something WAS created
  }
}

describe('TutorialUploadScreen — the create-failed case needs a way forward', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.editingRef = null
    h.uploadImpl = null
    h.uploadCalls = 0
  })

  it('PREMISE: an error surface already exists as of #1040', async () => {
    // Not a requirement, a probe. The work order said this beat had no error
    // surface at all; #1040 added one, so this records what is actually there
    // and keeps the rest of the suite honest about what is missing.
    h.uploadImpl = createFailedOutright()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    expect(wrapper.find('[data-testid="tutorial-upload-failure"]').exists()).toBe(true)
  })

  it('offers a RETRY control when the create failed outright', async () => {
    h.uploadImpl = createFailedOutright()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    expect(wrapper.find('[data-testid="tutorial-upload-retry"]').exists()).toBe(true)
  })

  it('retrying actually re-attempts the upload with the same file', async () => {
    // A button that renders but does not re-drive the upload would be the worst
    // of the three outcomes: it looks like a way forward and is not.
    h.uploadImpl = createFailedOutright()
    const wrapper = mountScreen(null)
    await dropFile(wrapper)
    expect(h.uploadCalls).toBe(1)

    // Second attempt succeeds, as a rate limit typically would.
    h.uploadImpl = () => {
      h.editingRef.value = { id: 'prod-1', name: 'sample-vision' }
      h.visionUploadError.value = null
      h.visionUploadRetrySafe.value = null
    }
    await wrapper.find('[data-testid="tutorial-upload-retry"]').trigger('click')
    await flushPromises()

    expect(h.uploadCalls).toBe(2)
    expect(h.stageAnalysis).toHaveBeenCalled()
    // And the beat moves on, because this time there is something to analyse.
    expect(wrapper.find('[data-testid="tutorial-drop-zone"]').exists()).toBe(false)
  })

  it('offers a manual escape, as door D does', async () => {
    // FE-9566's shape: a failure the operator cannot clear by retrying must not
    // be a dead end. Emitting `manual` is how door D hands them the form.
    h.uploadImpl = createFailedOutright()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)
    const escape = wrapper.find('[data-testid="tutorial-upload-manual"]')
    expect(escape.exists()).toBe(true)

    await escape.trigger('click')
    expect(wrapper.emitted('manual')).toBeTruthy()
  })

  it('a CLEAN-retry failure does not warn about duplicate products', async () => {
    // Nothing was created, so the operator must not be told to go and check
    // Products -- that is advice for the other failure, and following it here
    // wastes their time looking for something that does not exist.
    h.uploadImpl = createFailedOutright()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    const text = wrapper.find('[data-testid="tutorial-upload-failure"]').text()
    expect(text).not.toMatch(/was created|already exists|second/i)
  })

  it('the CREATED-but-unbound failure still warns, and offers no clean retry', async () => {
    // The #1040 case, asserted here so the two cannot converge on one message.
    // Retrying this one mints a second product, so the retry button must NOT
    // be the offered remedy.
    h.uploadImpl = createdButUnbound()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    const text = wrapper.find('[data-testid="tutorial-upload-failure"]').text()
    expect(text).toMatch(/product/i)
    expect(wrapper.find('[data-testid="tutorial-upload-retry"]').exists()).toBe(false)
  })

  it('the happy path is untouched (control)', async () => {
    h.uploadImpl = () => {
      h.editingRef.value = { id: 'prod-new', name: 'sample-vision' }
    }
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    expect(h.stageAnalysis).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="tutorial-upload-failure"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="tutorial-drop-zone"]').exists()).toBe(false)
  })
})
