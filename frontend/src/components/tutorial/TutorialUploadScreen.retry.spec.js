import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  editingRef: null,
  visionUploadError: null,
  visionUploadRetrySafe: null,
  uploadImpl: null,
  uploadCalls: 0,
  stageAnalysis: vi.fn(),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => null),
  }),
}))

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

function createFailedOutright(message = 'Too many requests. Wait a moment and try again.') {
  return () => {
    h.editingRef.value = null
    h.visionUploadError.value = message
    h.visionUploadRetrySafe.value = true
  }
}

function createdButUnbound() {
  return () => {
    h.editingRef.value = null
    h.visionUploadError.value =
      'A product was created but the file could not be attached to it. Open Products to see it, or try again from there.'
    h.visionUploadRetrySafe.value = false
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
    h.uploadImpl = createFailedOutright()
    const wrapper = mountScreen(null)
    await dropFile(wrapper)
    expect(h.uploadCalls).toBe(1)

    h.uploadImpl = () => {
      h.editingRef.value = { id: 'prod-1', name: 'sample-vision' }
      h.visionUploadError.value = null
      h.visionUploadRetrySafe.value = null
    }
    await wrapper.find('[data-testid="tutorial-upload-retry"]').trigger('click')
    await flushPromises()

    expect(h.uploadCalls).toBe(2)
    expect(h.stageAnalysis).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="tutorial-drop-zone"]').exists()).toBe(false)
  })

  it('offers a manual escape, as door D does', async () => {
    h.uploadImpl = createFailedOutright()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)
    const escape = wrapper.find('[data-testid="tutorial-upload-manual"]')
    expect(escape.exists()).toBe(true)

    await escape.trigger('click')
    expect(wrapper.emitted('manual')).toBeTruthy()
  })

  it('a CLEAN-retry failure does not warn about duplicate products', async () => {
    h.uploadImpl = createFailedOutright()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    const text = wrapper.find('[data-testid="tutorial-upload-failure"]').text()
    expect(text).not.toMatch(/was created|already exists|second/i)
  })

  it('the CREATED-but-unbound failure still warns, and offers no clean retry', async () => {
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
