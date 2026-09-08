/**
 * TutorialPromptScreen.create-failure.spec.js — FE-9566
 *
 * Door D pre-creates the product card the agent will fill in. Every failure on
 * that path used to be swallowed by three empty catches: if both creates were
 * rejected, `activeProductId` was set to '' and the screen carried on as if
 * nothing had happened — no error, no retry, no log. The user was left looking
 * at a prompt whose product does not exist, and the prompt itself is actively
 * harmful in that state: buildPromptD interpolates the id, so a blank one
 * produces `product_id is ""` for the user to copy and paste at their agent.
 *
 * The same silence made a failed create and a create that never ran
 * indistinguishable from the outside — a rejected POST is invisible to any
 * observer that only watches for successful responses.
 *
 * Edition scope: Both (shared frontend/src).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  row: null,
  products: [],
  createProduct: null,
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: h.products,
    fetchProductById: vi.fn(async () => h.row),
    createProduct: h.createProduct,
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

/** Door D with NO threaded product id — the create-or-adopt path. */
function mountDoorD() {
  return mount(TutorialPromptScreen, {
    props: { path: 'D', productId: null },
    global: { stubs },
  })
}

const ERROR = '[data-testid="tutorial-prompt-error"]'
const RETRY = '[data-testid="tutorial-prompt-retry"]'
const COPY = '[data-testid="tutorial-copy-prompt"]'
const WAITING = '[data-testid="tutorial-agent-waiting"]'

describe('TutorialPromptScreen — door D says so when it cannot get a product (FE-9566)', () => {
  beforeEach(() => {
    h.row = { id: 'prod-1', consolidated_vision_light: '' }
    h.products = []
    h.createProduct = vi.fn(async () => ({ id: 'prod-1' }))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows an error with a retry when BOTH creates are rejected', async () => {
    h.createProduct = vi.fn(async () => {
      throw new Error("Product '' already exists")
    })
    const wrapper = mountDoorD()
    await flushPromises()

    // Both the empty-name create and the "My product" fallback were tried.
    expect(h.createProduct).toHaveBeenCalledTimes(2)

    const err = wrapper.find(ERROR)
    expect(err.exists()).toBe(true)
    expect(err.text()).toMatch(/could not|couldn't|unable/i)
    expect(wrapper.find(RETRY).exists()).toBe(true)

    // It must NOT pretend a product exists.
    expect(wrapper.emitted('product-created')).toBeUndefined()
    // And it must not simultaneously claim to be waiting on an agent.
    expect(wrapper.find(WAITING).exists()).toBe(false)
  })

  it('does not offer a prompt to copy while there is no product to fill in', async () => {
    h.createProduct = vi.fn(async () => {
      throw new Error('boom')
    })
    const wrapper = mountDoorD()
    await flushPromises()

    // buildPromptD would interpolate an empty product_id — copying that sends
    // the user's agent at a product that does not exist.
    expect(wrapper.find(COPY).attributes('disabled')).toBeDefined()
  })

  it('logs the give-up instead of swallowing it', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    h.createProduct = vi.fn(async () => {
      throw new Error('the underlying reason')
    })
    mountDoorD()
    await flushPromises()

    expect(spy).toHaveBeenCalled()
    const logged = spy.mock.calls.map((c) => c.map(String).join(' ')).join('\n')
    expect(logged).toMatch(/the underlying reason/)
  })

  it('treats a create that resolves WITHOUT an id as a failure, not a success', async () => {
    // The store returns response.data, which can be null — the old code turned
    // that into activeProductId='' and carried on silently, same as a throw.
    h.createProduct = vi.fn(async () => null)
    const wrapper = mountDoorD()
    await flushPromises()

    expect(wrapper.find(ERROR).exists()).toBe(true)
    expect(wrapper.emitted('product-created')).toBeUndefined()
  })

  it('retry re-attempts and clears the error once a create succeeds', async () => {
    let attempt = 0
    h.createProduct = vi.fn(async () => {
      attempt += 1
      // First mount: both the create and its fallback fail. Then it recovers.
      if (attempt <= 2) throw new Error('transient')
      return { id: 'prod-9' }
    })
    const wrapper = mountDoorD()
    await flushPromises()
    expect(wrapper.find(ERROR).exists()).toBe(true)

    await wrapper.find(RETRY).trigger('click')
    await flushPromises()

    expect(wrapper.find(ERROR).exists()).toBe(false)
    expect(wrapper.emitted('product-created')).toHaveLength(1)
    expect(wrapper.emitted('product-created')[0]).toEqual(['prod-9'])
    expect(wrapper.find(COPY).attributes('disabled')).toBeUndefined()
  })

  it('the healthy path is untouched — no error, product emitted, prompt copyable', async () => {
    const wrapper = mountDoorD()
    await flushPromises()

    expect(wrapper.find(ERROR).exists()).toBe(false)
    expect(wrapper.emitted('product-created')).toHaveLength(1)
    expect(wrapper.emitted('product-created')[0]).toEqual(['prod-1'])
    expect(wrapper.find(COPY).attributes('disabled')).toBeUndefined()
  })

  it('adopting an existing empty draft still short-circuits without creating', async () => {
    h.products = [{ id: 'draft-7', is_active: false, name: '' }]
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).not.toHaveBeenCalled()
    expect(wrapper.find(ERROR).exists()).toBe(false)
    expect(wrapper.emitted('product-created')[0]).toEqual(['draft-7'])
  })
})
