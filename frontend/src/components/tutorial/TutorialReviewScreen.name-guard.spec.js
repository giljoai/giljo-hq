import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  row: null,
  updateProduct: vi.fn(async () => ({})),
  toggleProductActivation: vi.fn(async () => {}),
}))

const cache = ref({})

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => {
      if (h.row) cache.value = { ...cache.value, [h.row.id]: h.row }
      return h.row
    }),
    fetchProducts: vi.fn(async () => []),
    updateProduct: h.updateProduct,
    getProductById: (id) => (id ? cache.value[id] || null : null),
    activeProduct: null,
  }),
}))

vi.mock('@/composables/useProductActivation', () => ({
  useProductActivation: () => ({
    toggleProductActivation: h.toggleProductActivation,
  }),
}))

import TutorialReviewScreen from './TutorialReviewScreen.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': {
    template: '<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
    props: ['disabled'],
    emits: ['click'],
  },
}

async function mountReview() {
  const wrapper = mount(TutorialReviewScreen, {
    props: { productId: 'prod-1' },
    global: { stubs },
  })
  await flushPromises()
  return wrapper
}

const NAMED = { id: 'prod-1', name: 'Real Product', tech_stack: {}, is_active: false }
const NAMELESS = { id: 'prod-1', name: '', tech_stack: {}, is_active: false }

describe('TutorialReviewScreen — a nameless product cannot be activated (FE-9320)', () => {
  beforeEach(() => {
    h.row = NAMED
    h.updateProduct = vi.fn(async (id, updates) => {
      cache.value = { ...cache.value, [id]: { ...(cache.value[id] || {}), ...updates } }
      return cache.value[id]
    })
    h.toggleProductActivation = vi.fn(async () => {})
    cache.value = {}
  })

  it('a named product activates as before — no prompt, no extra write', async () => {
    const wrapper = await mountReview()

    expect(wrapper.find('[data-testid="tutorial-name-required"]').exists()).toBe(false)

    await wrapper.find('[data-testid="tutorial-activate"]').trigger('click')
    await flushPromises()

    expect(h.updateProduct).not.toHaveBeenCalled()
    expect(h.toggleProductActivation).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('activated')).toHaveLength(1)
  })

  it('a nameless product asks for a name and blocks Activate until it has one', async () => {
    h.row = NAMELESS
    const wrapper = await mountReview()

    expect(wrapper.find('[data-testid="tutorial-name-required"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="tutorial-activate"]').attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="tutorial-product-name-input"]').setValue('   ')
    expect(wrapper.find('[data-testid="tutorial-activate"]').attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="tutorial-product-name-input"]').setValue('  My Real Product  ')
    expect(wrapper.find('[data-testid="tutorial-activate"]').attributes('disabled')).toBeUndefined()
  })

  it('saves the trimmed name before activating', async () => {
    h.row = NAMELESS
    const wrapper = await mountReview()

    await wrapper.find('[data-testid="tutorial-product-name-input"]').setValue('  My Real Product  ')
    await wrapper.find('[data-testid="tutorial-activate"]').trigger('click')
    await flushPromises()

    expect(h.updateProduct).toHaveBeenCalledWith('prod-1', { name: 'My Real Product' })
    expect(h.toggleProductActivation).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('activated')).toHaveLength(1)
  })

  it('does NOT activate when saving the name fails', async () => {
    h.row = NAMELESS
    h.updateProduct = vi.fn(async () => {
      throw new Error('network down')
    })
    const wrapper = await mountReview()

    await wrapper.find('[data-testid="tutorial-product-name-input"]').setValue('My Real Product')
    await wrapper.find('[data-testid="tutorial-activate"]').trigger('click')
    await flushPromises()

    expect(h.toggleProductActivation).not.toHaveBeenCalled()
    expect(wrapper.emitted('activated')).toBeFalsy()
    expect(wrapper.find('[data-testid="tutorial-name-error"]').exists()).toBe(true)
  })
})
