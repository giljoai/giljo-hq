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


function documentFailed(message = 'sample-vision.md: Too many requests. Wait a moment and try again.') {
  return () => {
    h.editingRef.value = { id: 'prod-1', name: 'sample-vision' }
    h.visionUploadError.value = message
    h.visionUploadRetrySafe.value = true
  }
}

describe('TutorialUploadScreen — product created but the document upload failed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.editingRef = null
    h.uploadImpl = null
    h.uploadCalls = 0
  })

  it('shows the failure and does not claim the document was uploaded', async () => {
    h.uploadImpl = documentFailed()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    expect(h.stageAnalysis).not.toHaveBeenCalled()
    const failure = wrapper.find('[data-testid="tutorial-upload-failure"]')
    expect(failure.exists()).toBe(true)
    expect(failure.text()).toMatch(/Too many requests/)
    expect(wrapper.find('[data-testid="tutorial-drop-zone"]').exists()).toBe(true)
  })

  it('hands the created product to the state machine so a retry reuses it', async () => {
    h.uploadImpl = documentFailed()
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    expect(wrapper.emitted('product-created')).toEqual([['prod-1']])
  })

  it('offers a retry that re-posts to the same product and then advances', async () => {
    h.uploadImpl = documentFailed()
    const wrapper = mountScreen(null)
    await dropFile(wrapper)

    const seen = []
    h.uploadImpl = () => {
      seen.push(h.editingRef.value?.id)
      h.visionUploadError.value = null
      h.visionUploadRetrySafe.value = null
    }
    await wrapper.find('[data-testid="tutorial-upload-retry"]').trigger('click')
    await flushPromises()

    expect(seen).toEqual(['prod-1'])
    expect(wrapper.emitted('product-created')).toHaveLength(1)
    expect(h.stageAnalysis).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="tutorial-upload-failure"]').exists()).toBe(false)
  })
})
