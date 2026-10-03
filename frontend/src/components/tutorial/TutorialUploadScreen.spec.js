import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  fetchResult: null,
  editingRef: null,
  uploadImpl: null,
  stageAnalysis: vi.fn(),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => h.fetchResult),
  }),
}))

vi.mock('@/composables/useProductVisionUpload', () => ({
  useProductVisionUpload: ({ editingProduct }) => {
    h.editingRef = editingProduct
    return {
      uploadingVision: ref(false),
      visionUploadError: ref(null),
      visionUploadRetrySafe: ref(null),
      uploadVisionFilesOnAttach: vi.fn(async (args) => h.uploadImpl?.(args)),
    }
  },
}))

vi.mock('@/composables/useVisionAnalysis', () => ({
  useVisionAnalysis: () => ({
    promptFallbackText: ref(''),
    analysisHintVisible: ref(false),
    stageAnalysis: (...a) => h.stageAnalysis(...a),
    onVisionAnalysisComplete: vi.fn(),
    resetAnalysisState: vi.fn(),
  }),
}))

import TutorialUploadScreen from './TutorialUploadScreen.vue'

function mountScreen(productId) {
  return mount(TutorialUploadScreen, {
    props: { productId },
    global: { stubs: { 'v-icon': true, 'v-btn': true } },
  })
}

async function dropFile(wrapper) {
  const file = new File(['vision body'], 'vision.md', { type: 'text/markdown' })
  await wrapper
    .find('[data-testid="tutorial-drop-zone"]')
    .trigger('drop', { dataTransfer: { files: [file] } })
  await flushPromises()
}

describe('TutorialUploadScreen — stale run-owned draft (TSK-9206)', () => {
  beforeEach(() => {
    h.fetchResult = null
    h.editingRef = null
    h.uploadImpl = null
    h.stageAnalysis = vi.fn()
  })

  it('drops the stale stub and invalidates the run product when the draft is gone', async () => {
    h.fetchResult = null
    const wrapper = mountScreen('dead-id')
    await flushPromises()

    expect(wrapper.emitted('product-invalidated')).toBeTruthy()
  })

  it('after invalidation, the next upload creates a FRESH product (never targets the dead id)', async () => {
    h.fetchResult = null
    h.uploadImpl = () => {
      h.editingRef.value = { id: 'fresh-id', name: 'vision' }
    }
    const wrapper = mountScreen('dead-id')
    await flushPromises()

    await dropFile(wrapper)

    const created = wrapper.emitted('product-created')
    expect(created).toBeTruthy()
    expect(created.at(-1)).toEqual(['fresh-id'])
    expect(h.stageAnalysis).toHaveBeenCalledWith(expect.anything(), 'fresh-id')
    expect(h.stageAnalysis).not.toHaveBeenCalledWith(expect.anything(), 'dead-id')
  })

  it('happy path: an existing run-owned product is adopted and reused (no invalidation, edit branch)', async () => {
    h.fetchResult = { id: 'live-id', name: 'Live Product' }
    h.uploadImpl = () => {}
    const wrapper = mountScreen('live-id')
    await flushPromises()

    expect(wrapper.emitted('product-invalidated')).toBeFalsy()

    await dropFile(wrapper)

    expect(wrapper.emitted('product-created')).toBeFalsy()
    expect(h.stageAnalysis).toHaveBeenCalledWith(expect.anything(), 'live-id')
  })
})
