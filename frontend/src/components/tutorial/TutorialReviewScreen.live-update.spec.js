import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

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
