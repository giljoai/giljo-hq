import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  editingRef: null,
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

vi.mock('@/composables/useProductVisionUpload', () => ({
  useProductVisionUpload: ({ editingProduct }) => {
    h.editingRef = editingProduct
    h.visionUploadError = ref(null)
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
    h.uploadImpl = () => {
      h.createdServerSide = true
      h.editingRef.value = null
      h.visionUploadError.value =
        'A product was created but the file could not be attached to it. Open Products to see it, or try again from there.'
      h.visionUploadRetrySafe.value = false
    }
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    expect(h.createdServerSide).toBe(true)
    expect(wrapper.find('[data-testid="tutorial-upload-failure"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="tutorial-upload-failure"]').text()).toMatch(/product/i)
    expect(stillOnDropZone(wrapper)).toBe(true)
  })

  it('surfaces something to the operator rather than failing silently', async () => {
    h.uploadImpl = () => {
      h.createdServerSide = true
      h.editingRef.value = null
      h.visionUploadError.value =
        'A product was created but the file could not be attached to it. Open Products to see it, or try again from there.'
      h.visionUploadRetrySafe.value = false
    }
    const wrapper = mountScreen(null)

    await dropFile(wrapper)

    const text = wrapper.text()
    const saysSomething = /again|problem|could not|couldn't|failed|retry/i.test(text)
    expect(saysSomething || !stillOnDropZone(wrapper)).toBe(true)
  })
})
