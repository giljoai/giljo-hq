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
  useClipboard: () => ({ copy: vi.fn(async () => true) }),
}))

vi.mock('@/composables/useGiljoMode', () => ({
  useGiljoMode: () => ({ isSaasMode: () => false }),
}))

import TutorialPromptScreen from './TutorialPromptScreen.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': {
    template:
      '<button v-bind="$attrs" :data-variant="variant" :data-color="color" @click="$emit(\'click\', $event)"><slot /></button>',
    props: ['variant', 'color'],
    emits: ['click'],
  },
}

function mountPrompt(path = 'D', props = {}) {
  return mount(TutorialPromptScreen, {
    props: { path, productId: 'prod-1', ...props },
    global: { stubs },
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('TutorialPromptScreen — door D copy fix (FE-9569 Part 2)', () => {
  it('replaces the impossible "come back here" instruction with the refresh-in-place copy', async () => {
    h.row = { id: 'prod-1', name: '', description: '' }
    const wrapper = mountPrompt('D')
    await flushPromises()

    const text = wrapper.text()
    expect(text).not.toContain('Come back here when your agent reports done')
    expect(text).toContain('this screen will refresh when the agent finishes its proposal')
  })

  it('leaves the door B hint alone (no MCP connection needed, different flow)', async () => {
    const wrapper = mountPrompt('B')
    await flushPromises()
    expect(wrapper.text()).toContain('When you have your vision document, come back and upload it.')
  })
})

describe('TutorialPromptScreen — waiting-dot enhanced visibility (FE-9569 detector 3)', () => {
  it('shows the enhanced waiting indicator while nothing has landed yet', async () => {
    h.row = { id: 'prod-1', name: '', description: '' }
    const wrapper = mountPrompt('D')
    await flushPromises()

    expect(wrapper.find('[data-testid="tutorial-agent-waiting"]').exists()).toBe(true)
    expect(wrapper.find('.waiting-dot-ring').exists()).toBe(true)
  })

  it('the waiting indicator is gone once the agent reports done', async () => {
    h.row = { id: 'prod-1', name: 'Named', consolidated_vision_light: 'summary' }
    const wrapper = mountPrompt('D')
    await flushPromises()

    expect(wrapper.find('[data-testid="tutorial-agent-waiting"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(true)
  })
})

describe('TutorialPromptScreen — copy-prompt button demotes once agent activity is detected (FE-9569 Part 2)', () => {
  it('starts full-strength (primary/flat) before anything has landed', async () => {
    h.row = { id: 'prod-1', name: '', description: '' }
    const wrapper = mountPrompt('D')
    await flushPromises()

    const btn = wrapper.find('[data-testid="tutorial-copy-prompt"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('data-variant')).toBe('flat')
  })

  it('stays visible but demotes its styling once the agent starts populating the product', async () => {
    h.row = { id: 'prod-1', name: '', description: '' }
    const wrapper = mountPrompt('D')
    await flushPromises()

    h.row = { id: 'prod-1', name: 'agent-named', description: 'Populated by the agent.' }
    await vi.advanceTimersByTimeAsync(10_000)
    await flushPromises()

    const btn = wrapper.find('[data-testid="tutorial-copy-prompt"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('data-variant')).not.toBe('flat')
  })

  it('demotes from a tech_stack-only write too (activity can land in any section first)', async () => {
    h.row = { id: 'prod-1', name: '', description: '' }
    const wrapper = mountPrompt('D')
    await flushPromises()

    h.row = { id: 'prod-1', name: '', description: '', tech_stack: { programming_languages: 'Python' } }
    await vi.advanceTimersByTimeAsync(10_000)
    await flushPromises()

    expect(wrapper.find('[data-testid="tutorial-copy-prompt"]').attributes('data-variant')).not.toBe('flat')
  })
})
