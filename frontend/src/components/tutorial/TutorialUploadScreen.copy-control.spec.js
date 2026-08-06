/**
 * TutorialUploadScreen.copy-control.spec.js — FE-9320
 *
 * Operator's rule: a prompt reaches the clipboard ONLY via a distinct button or
 * the copy icon beside the text. NEVER as a side effect of another action.
 *
 * The regression: dropping a vision document called stageAnalysis, which wrote
 * the discovery prompt straight to the clipboard. The user never asked for it,
 * and when the write failed the wizard showed an unexplained fallback panel.
 *
 * These tests run the REAL useVisionAnalysis composable — stubbing it would make
 * the central claim ("attaching a file does not copy") a statement about the
 * mock rather than about the screen.
 *
 * Edition scope: Both (shared frontend/src).
 */
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
  // stageAnalysis starts a real 10s poll interval and a real 60s hint timeout.
  // Without fake timers those outlive the file and race vitest worker teardown
  // under xdist — the flake class tests/setup.js already documents. The sibling
  // FE-9320 specs fake their timers for the same reason.
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
    // The real prompt the agent needs — not a "clipboard blocked" fallback.
    expect(box.text()).toContain('get_vision_doc(product_id="prod-1")')
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
    expect(h.copy.mock.calls[0][0]).toContain('get_vision_doc(product_id="prod-1")')
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
