/**
 * TutorialReviewScreen.live-update.spec.js — FE-9569
 *
 * The operator's open question: "not sure if the proposal changes on screen
 * even if the user asked to update it." Answer: it did NOT. `product` used to
 * be a local `ref(null)` snapshotted once in onMounted and never looked at
 * the store again. The store itself IS live -- systemEventRoutes'
 * vision:analysis_complete handler (fired on every update_product_context
 * write, per TutorialPromptScreen.vue's own doc comment) and
 * stores/products.js's updateProduct() both write-through into
 * productsById -- so an agent revision arriving while the user sits on this
 * screen was invisible, letting them approve stale text.
 *
 * Fix: derive `product` from productStore.getProductById(id), a REACTIVE
 * getter, instead of a local snapshot. This spec proves the live-update by
 * mutating the same reactive cache the real store's getter reads from and
 * checking the DOM updates with no remount.
 *
 * Edition scope: Both (shared frontend/src).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

// A minimal stand-in for productStore.productsById -- a REAL Vue ref, so a
// component's `computed(() => productStore.getProductById(id))` tracks it
// exactly as it would the genuine Pinia store's own computed-of-function
// getter (stores/products.js:55).
const cache = ref({})

const h = vi.hoisted(() => ({
  toggleProductActivation: vi.fn(async () => {}),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async (id) => cache.value[id] || null),
    fetchProducts: vi.fn(async () => []),
    updateProduct: vi.fn(async () => ({})),
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

beforeEach(() => {
  cache.value = {}
})

describe('TutorialReviewScreen — live-updates from the store while the user is looking (FE-9569)', () => {
  it('re-renders the description when the store row changes AFTER mount, no remount needed', async () => {
    cache.value = {
      'p-1': { id: 'p-1', name: 'First Draft', description: 'v1', is_active: false, tech_stack: {} },
    }
    const wrapper = mount(TutorialReviewScreen, { props: { productId: 'p-1' }, global: { stubs } })
    await flushPromises()
    expect(wrapper.find('[data-testid="tutorial-review-description"]').text()).toBe('v1')

    // Simulate the agent revising the product via update_product_context
    // while the user is sitting on this screen -- systemEventRoutes'
    // vision:analysis_complete handler write-throughs into this SAME cache.
    cache.value = {
      ...cache.value,
      'p-1': { ...cache.value['p-1'], description: 'v2 -- tightened the tech stack per your ask' },
    }
    await flushPromises()

    expect(wrapper.find('[data-testid="tutorial-review-description"]').text()).toBe(
      'v2 -- tightened the tech stack per your ask',
    )
  })

  it('also picks up a tech-stack revision live', async () => {
    cache.value = {
      'p-1': {
        id: 'p-1',
        name: 'First Draft',
        description: 'v1',
        is_active: false,
        tech_stack: { programming_languages: 'Python' },
      },
    }
    const wrapper = mount(TutorialReviewScreen, { props: { productId: 'p-1' }, global: { stubs } })
    await flushPromises()
    expect(wrapper.find('[data-testid="tutorial-section-toggle-tech"]').text()).toContain('1 groups')

    cache.value = {
      ...cache.value,
      'p-1': { ...cache.value['p-1'], tech_stack: { programming_languages: 'Python, TypeScript' } },
    }
    await flushPromises()

    expect(wrapper.find('[data-testid="tutorial-section-fields-tech"]').text()).toContain('TypeScript')
  })
})
