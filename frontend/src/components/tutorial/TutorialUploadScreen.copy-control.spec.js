import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  copy: vi.fn(async () => true),
  editingRef: null,
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => ({ id: 'prod-1', name: 'Live Product' })),
    updateProduct: vi.fn(async () => ({})),
  }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: h.copy, copied: ref(false) }),
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

function mountScreen() {
  return mount(TutorialUploadScreen, {
    props: { productId: 'prod-1' },
    global: { stubs },
  })
}

async function dropFile(wrapper) {
  const file = new File(['vision body'], 'vision.md', { type: 'text/markdown' })
  await wrapper
    .find('[data-testid="tutorial-drop-zone"]')
    .trigger('drop', { dataTransfer: { files: [file] } })
  await flushPromises()
}

describe('TutorialUploadScreen — copying is the user\'s action, never a side effect (FE-9320)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    h.copy = vi.fn(async () => true)
    h.editingRef = null
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('attaching a document does NOT write to the clipboard', async () => {
    const wrapper = await mountScreen()
    await flushPromises()

    await dropFile(wrapper)

    expect(h.copy).not.toHaveBeenCalled()
  })

  it('shows the prompt by default, so it is readable without any copy attempt', async () => {
    const wrapper = await mountScreen()
    await flushPromises()
    await dropFile(wrapper)

    const box = wrapper.find('[data-testid="tutorial-analysis-prompt"]')
    expect(box.exists()).toBe(true)
    expect(box.text()).toContain('get_vision_document(product_id="prod-1")')
    expect(wrapper.text()).not.toContain('Clipboard blocked')
  })

  it('the explicit button copies exactly that prompt, once', async () => {
    const wrapper = await mountScreen()
    await flushPromises()
    await dropFile(wrapper)

    const btn = wrapper.find('[data-testid="tutorial-copy-analysis-prompt"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('Copy discovery prompt')

    await btn.trigger('click')
    await flushPromises()

    expect(h.copy).toHaveBeenCalledTimes(1)
    expect(h.copy.mock.calls[0][0]).toContain('get_vision_document(product_id="prod-1")')
    expect(wrapper.find('[data-testid="tutorial-copy-analysis-prompt"]').text()).toContain('Copied')
  })

  it('a FAILED copy does not claim the prompt was copied', async () => {
    h.copy = vi.fn(async () => false)
    const wrapper = await mountScreen()
    await flushPromises()
    await dropFile(wrapper)

    await wrapper.find('[data-testid="tutorial-copy-analysis-prompt"]').trigger('click')
    await flushPromises()

    expect(h.copy).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="tutorial-copy-analysis-prompt"]').text()).not.toContain('Copied')
  })
})
