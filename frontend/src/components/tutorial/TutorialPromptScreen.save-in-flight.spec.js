import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  row: null,
  products: [],
  createProduct: null,
  copy: null,
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: h.products,
    fetchProductById: vi.fn(async () => h.row),
    createProduct: h.createProduct,
  }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: h.copy, copied: { value: false } }),
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

const COPY = '[data-testid="tutorial-copy-prompt"]'
const SAVING = '[data-testid="tutorial-prompt-saving"]'
const WAITING = '[data-testid="tutorial-agent-waiting"]'

function deferredCreate() {
  let resolve
  const promise = new Promise((r) => {
    resolve = r
  })
  h.createProduct = vi.fn(() => promise)
  return { resolve }
}

function mountDoorD() {
  return mount(TutorialPromptScreen, {
    props: { path: 'D', productId: null },
    global: { stubs },
  })
}

describe('TutorialPromptScreen: door D Copy waits for the product save', () => {
  beforeEach(() => {
    h.row = { id: 'prod-1', consolidated_vision_light: '' }
    h.products = []
    h.copy = vi.fn(async () => true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps Copy disabled, with a stated reason, while the save is in flight', async () => {
    deferredCreate()
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).toHaveBeenCalledTimes(1)
    const btn = wrapper.find(COPY)
    expect(btn.attributes('disabled')).toBeDefined()

    const saving = wrapper.find(SAVING)
    expect(saving.exists()).toBe(true)
    expect(saving.text()).toMatch(/saving your product/i)
    expect(btn.attributes('aria-describedby')).toBe(saving.attributes('id'))
    expect(wrapper.find(WAITING).exists()).toBe(false)
  })

  it('never copies a prompt with an empty product id while the save is in flight', async () => {
    deferredCreate()
    const wrapper = mountDoorD()
    await flushPromises()

    await wrapper.find(COPY).trigger('click')
    const copyPrompt = wrapper.vm.$.setupState.copyPrompt
    expect(typeof copyPrompt).toBe('function')
    await copyPrompt()
    await flushPromises()

    expect(h.copy).not.toHaveBeenCalled()
  })

  it('enables Copy with the real id once the save resolves', async () => {
    const { resolve } = deferredCreate()
    const wrapper = mountDoorD()
    await flushPromises()
    expect(wrapper.find(COPY).attributes('disabled')).toBeDefined()

    resolve({ id: 'prod-42' })
    await flushPromises()

    const btn = wrapper.find(COPY)
    expect(btn.attributes('disabled')).toBeUndefined()
    expect(btn.attributes('aria-describedby')).toBeUndefined()
    expect(wrapper.find(SAVING).exists()).toBe(false)
    expect(wrapper.find(WAITING).exists()).toBe(true)

    await btn.trigger('click')
    await flushPromises()
    expect(h.copy).toHaveBeenCalledTimes(1)
    expect(String(h.copy.mock.calls[0][0])).toContain('prod-42')
  })

  it('a threaded product id is copyable at once, with no saving state', async () => {
    h.createProduct = vi.fn()
    const wrapper = mount(TutorialPromptScreen, {
      props: { path: 'D', productId: 'prod-threaded' },
      global: { stubs },
    })
    await flushPromises()

    expect(h.createProduct).not.toHaveBeenCalled()
    expect(wrapper.find(COPY).attributes('disabled')).toBeUndefined()
    expect(wrapper.find(SAVING).exists()).toBe(false)
  })

  it('door B has no product to save and is never gated', async () => {
    h.createProduct = vi.fn()
    const wrapper = mount(TutorialPromptScreen, {
      props: { path: 'B' },
      global: { stubs },
    })
    await flushPromises()

    expect(wrapper.find(COPY).attributes('disabled')).toBeUndefined()
    expect(wrapper.find(SAVING).exists()).toBe(false)
  })
})
