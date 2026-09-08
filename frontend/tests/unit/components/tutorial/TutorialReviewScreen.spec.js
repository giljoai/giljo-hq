/**
 * Unit tests for TutorialReviewScreen (FE-9200, audit F1) — product identity:
 * the screen renders ONLY the run-owned threaded product (never products[0],
 * which is the user's real active product), and Activate can never flow into
 * toggleProductActivation's deactivation branch.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { ref } from 'vue'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// FE-9569: a REAL Vue ref backing getProductById, so the component's
// `computed(() => productStore.getProductById(id))` tracks it the same way
// it tracks the genuine store's own computed-of-function getter
// (stores/products.js:55) -- not just a one-shot local snapshot.
const cache = ref({})

const mockProductStore = {
  products: [
    { id: 'alpha-active', name: 'Alpha', description: 'Real product', is_active: true },
  ],
  activeProduct: { id: 'alpha-active', name: 'Alpha' },
  fetchProducts: vi.fn(async () => {}),
  fetchProductById: vi.fn(async (id) => {
    const row = {
      id,
      name: 'Draft Product',
      description: 'Proposed by the agent.',
      is_active: false,
      tech_stack: {},
    }
    cache.value = { ...cache.value, [id]: row }
    return row
  }),
  getProductById: (id) => (id ? cache.value[id] || null : null),
}

vi.mock('@/stores/products', () => ({
  useProductStore: () => mockProductStore,
}))

const mockToggle = vi.fn(async () => {})
const mockConfirm = vi.fn(async () => {})
vi.mock('@/composables/useProductActivation', async () => {
  const { ref } = await import('vue')
  return {
    useProductActivation: () => ({
      showActivationWarning: ref(false),
      pendingActivation: ref(null),
      currentActiveProduct: ref(null),
      toggleProductActivation: mockToggle,
      confirmActivation: mockConfirm,
      cancelActivation: vi.fn(),
    }),
  }
})

import TutorialReviewScreen from '@/components/tutorial/TutorialReviewScreen.vue'

const vuetify = createVuetify({ components, directives })

function mountScreen(props = {}) {
  return mount(TutorialReviewScreen, {
    props,
    global: {
      plugins: [vuetify],
      stubs: {
        ActivationWarningDialog: true,
      },
    },
  })
}

describe('TutorialReviewScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    cache.value = {}
    mockProductStore.activeProduct = { id: 'alpha-active', name: 'Alpha' }
    mockProductStore.fetchProductById.mockImplementation(async (id) => {
      const row = {
        id,
        name: 'Draft Product',
        description: 'Proposed by the agent.',
        is_active: false,
        tech_stack: {},
      }
      cache.value = { ...cache.value, [id]: row }
      return row
    })
  })

  it('renders the THREADED product, never products[0] (audit F1)', async () => {
    const wrapper = mountScreen({ productId: 'draft-1' })
    await flushPromises()

    expect(mockProductStore.fetchProductById).toHaveBeenCalledWith('draft-1')
    expect(wrapper.text()).toContain('Draft Product')
    expect(wrapper.text()).not.toContain('Alpha')
  })

  it('renders the empty state with Activate disabled when no product is threaded', async () => {
    const wrapper = mountScreen()
    await flushPromises()

    expect(mockProductStore.fetchProductById).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="tutorial-activate"]').attributes('disabled')).toBeDefined()
  })

  it('Activate on the inactive draft goes through the activation flow', async () => {
    const wrapper = mountScreen({ productId: 'draft-1' })
    await flushPromises()

    await wrapper.find('[data-testid="tutorial-activate"]').trigger('click')
    await flushPromises()

    expect(mockToggle).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('activated')).toBeTruthy()
  })

  it('Activate on an ALREADY-ACTIVE product never calls the toggle (deactivation guard)', async () => {
    mockProductStore.fetchProductById.mockImplementation(async (id) => {
      const row = {
        id,
        name: 'Draft Product',
        description: 'Activated mid-flow from the Products page.',
        is_active: true,
        tech_stack: {},
      }
      cache.value = { ...cache.value, [id]: row }
      return row
    })
    const wrapper = mountScreen({ productId: 'draft-1' })
    await flushPromises()

    await wrapper.find('[data-testid="tutorial-activate"]').trigger('click')
    await flushPromises()

    expect(mockToggle).not.toHaveBeenCalled()
    expect(wrapper.emitted('activated')).toBeTruthy()
  })
})
