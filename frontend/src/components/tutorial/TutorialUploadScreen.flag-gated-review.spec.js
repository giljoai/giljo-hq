import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  row: null,
  editingRef: null,
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => h.row),
    updateProduct: vi.fn(async () => ({})),
  }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(async () => true), copied: ref(false) }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

vi.mock('@/composables/useProductVisionUpload', () => ({
  useProductVisionUpload: ({ editingProduct }) => {
    h.editingRef = editingProduct
    return {
      uploadingVision: ref(false),
      visionUploadError: ref(null),
      visionUploadRetrySafe: ref(null),
      uploadVisionFilesOnAttach: vi.fn(async () => {
        h.editingRef.value = { id: 'prod-1', name: 'Live Product' }
      }),
    }
  },
}))

import TutorialUploadScreen from './TutorialUploadScreen.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': {
    template: '<button v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
    emits: ['click'],
  },
}

const row = (complete) => ({ id: 'prod-1', name: 'Live Product', vision_analysis_complete: complete })

async function mountAndDrop() {
  const wrapper = mount(TutorialUploadScreen, { props: { productId: 'prod-1' }, global: { stubs } })
  await flushPromises()
  const file = new File(['vision body'], 'vision.md', { type: 'text/markdown' })
  await wrapper.find('[data-testid="tutorial-drop-zone"]').trigger('drop', { dataTransfer: { files: [file] } })
  await flushPromises()
  return wrapper
}

function emitServerEvent(complete) {
  window.dispatchEvent(
    new CustomEvent('vision-analysis-complete', {
      detail: { product_id: 'prod-1', fields_written: 2, vision_analysis_complete: complete },
    }),
  )
}

describe('TutorialUploadScreen — moves to the agent report only when the analysis is complete (FE-9794)', () => {
  let wrapper

  beforeEach(() => {
    vi.useFakeTimers()
    h.row = row(false)
    h.editingRef = null
  })

  afterEach(() => {
    wrapper?.unmount()
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('an intermediate write (flag false) keeps the screen waiting', async () => {
    wrapper = await mountAndDrop()

    emitServerEvent(false)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(20_000)

    expect(wrapper.emitted('review')).toBeUndefined()
    expect(wrapper.find('[data-testid="tutorial-analysis-panel"]').exists()).toBe(true)
  })

  it('the write that completes the analysis advances to the report, once', async () => {
    wrapper = await mountAndDrop()

    emitServerEvent(false)
    await flushPromises()
    h.row = row(true)
    emitServerEvent(true)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(20_000)

    expect(wrapper.emitted('review')).toHaveLength(1)
  })
})
