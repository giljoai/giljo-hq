import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ row: null }))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: [],
    fetchProductById: vi.fn(async () => h.row),
    createProduct: vi.fn(async () => ({ id: 'prod-1' })),
  }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(async () => true), copied: { value: false } }),
}))

vi.mock('@/composables/useGiljoMode', () => ({
  useGiljoMode: () => ({ isSaasMode: () => false }),
}))

import TutorialPromptScreen from './TutorialPromptScreen.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': {
    template: '<button v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
    emits: ['click'],
  },
}

function mountPrompt(path) {
  return mount(TutorialPromptScreen, {
    props: { path, productId: 'prod-1' },
    global: { stubs },
  })
}

const STALLED = '[data-testid="tutorial-prompt-stalled"]'

describe('TutorialPromptScreen — the existing-codebase door is honest when nothing comes back (FE-9320)', () => {
  beforeEach(() => {
    h.row = { id: 'prod-1', consolidated_vision_light: '' }
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('says nothing at first — it is normal for this to take a while', async () => {
    const wrapper = mountPrompt('D')
    await flushPromises()

    expect(wrapper.find(STALLED).exists()).toBe(false)
  })

  it('after a minute with no agent, names the actual requirement and offers a way out', async () => {
    const wrapper = mountPrompt('D')
    await flushPromises()

    await vi.advanceTimersByTimeAsync(60_000)

    const stalled = wrapper.find(STALLED)
    expect(stalled.exists()).toBe(true)
    expect(stalled.text()).toMatch(/connected to Giljo HQ/i)
    expect(stalled.text()).toMatch(/skipped the connect step/i)

    await wrapper.find('[data-testid="tutorial-prompt-manual"]').trigger('click')
    expect(wrapper.emitted('manual')).toHaveLength(1)
  })

  it('does not nag when the agent DID report done', async () => {
    h.row = { id: 'prod-1', consolidated_vision_light: 'a real summary' }
    const wrapper = mountPrompt('D')
    await flushPromises()

    await vi.advanceTimersByTimeAsync(60_000)

    expect(wrapper.find(STALLED).exists()).toBe(false)
  })

  it('leaves the idea door alone — it needs no connection and has its own next step', async () => {
    const wrapper = mountPrompt('B')
    await flushPromises()

    await vi.advanceTimersByTimeAsync(60_000)

    expect(wrapper.find(STALLED).exists()).toBe(false)
    expect(wrapper.find('[data-testid="tutorial-b-upload"]').exists()).toBe(true)
  })
})
