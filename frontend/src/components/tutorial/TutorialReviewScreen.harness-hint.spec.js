import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  row: null,
}))

const cache = ref({})

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => {
      if (h.row) cache.value = { ...cache.value, [h.row.id]: h.row }
      return h.row
    }),
    fetchProducts: vi.fn(async () => []),
    updateProduct: vi.fn(async () => ({})),
    getProductById: (id) => (id ? cache.value[id] || null : null),
    activeProduct: null,
  }),
}))

vi.mock('@/composables/useProductActivation', () => ({
  useProductActivation: () => ({
    toggleProductActivation: vi.fn(async () => {}),
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

describe('TutorialReviewScreen — teaches the harness door alongside the [Done!] button (FE-9569 supersedes FE-9503b)', () => {
  beforeEach(() => {
    h.row = { id: 'prod-1', name: 'Real Product', tech_stack: {}, is_active: false }
    cache.value = {}
  })

  it('the button reads [Done!], not "Activate product" (FE-9569: Activate is no longer user-facing)', async () => {
    const wrapper = await mountReview()
    const btn = wrapper.find('[data-testid="tutorial-activate"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toBe('Done!')
    expect(btn.text().toLowerCase()).not.toContain('activate')
  })

  it('the post-button subtitle mentions BOTH the agent (harness) and the app (dashboard) paths', async () => {
    const wrapper = await mountReview()
    const hint = wrapper.find('[data-testid="tutorial-review-post-hint"]')
    expect(hint.exists()).toBe(true)
    const text = hint.text().toLowerCase()
    expect(text).toMatch(/agent/)
    expect(text).toContain('/products')
  })

  it('names the product in the /products pointer', async () => {
    const wrapper = await mountReview()
    expect(wrapper.find('[data-testid="tutorial-review-post-hint"]').text()).toContain('Real Product')
  })

  it('the [Done!] button is still present and enabled — the subtitle never replaces it', async () => {
    const wrapper = await mountReview()
    const btn = wrapper.find('[data-testid="tutorial-activate"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('the subtitle is not a toggle or a control — no input, no button inside it', async () => {
    const wrapper = await mountReview()
    const hint = wrapper.find('[data-testid="tutorial-review-post-hint"]')
    expect(hint.findAll('input, button, select').length).toBe(0)
  })

  it('the old separate harness-hint element is gone (consolidated into the one subtitle)', async () => {
    const wrapper = await mountReview()
    expect(wrapper.find('[data-testid="tutorial-activate-harness-hint"]').exists()).toBe(false)
  })
})
