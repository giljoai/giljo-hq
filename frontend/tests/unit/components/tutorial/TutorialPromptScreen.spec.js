/**
 * Unit tests for TutorialPromptScreen (FE-9200) — per CODE_GUIDANCE §7:
 * edition variants (CE vs SaaS wording, mocked useGiljoMode), the copy button,
 * path-D product ensure + populated-card poll → review, path-B upload hand-off.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

let mockIsSaas = false
vi.mock('@/composables/useGiljoMode', () => ({
  useGiljoMode: () => ({
    isSaasMode: () => mockIsSaas,
    isCeMode: () => !mockIsSaas,
    isNonCeMode: () => mockIsSaas,
    getMode: () => (mockIsSaas ? 'saas' : 'ce'),
  }),
}))

const mockCopy = vi.fn(async () => true)
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: mockCopy }),
}))

const mockProductStore = {
  products: [],
  get hasProducts() {
    return this.products.length > 0
  },
  createProduct: vi.fn(async (payload) => {
    const product = { id: 'prod-uuid-1', name: payload.name, description: '' }
    mockProductStore.products.push(product)
    return product
  }),
  fetchProductById: vi.fn(async () => ({ id: 'prod-uuid-1', name: '', description: '' })),
}

vi.mock('@/stores/products', () => ({
  useProductStore: () => mockProductStore,
}))

import TutorialPromptScreen from '@/components/tutorial/TutorialPromptScreen.vue'

const vuetify = createVuetify({ components, directives })

function mountScreen(props = {}) {
  return mount(TutorialPromptScreen, {
    props: { path: 'D', ...props },
    global: { plugins: [vuetify] },
  })
}

describe('TutorialPromptScreen', () => {
  beforeEach(() => {
    mockIsSaas = false
    mockProductStore.products = []
    mockProductStore.createProduct.mockClear()
    mockProductStore.fetchProductById.mockClear()
    mockProductStore.fetchProductById.mockImplementation(async () => ({
      id: 'prod-uuid-1',
      name: '',
      description: '',
    }))
    mockCopy.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('path D', () => {
    it('silently ensures a product with an EXPLICIT empty name and embeds its UUID', async () => {
      const wrapper = mountScreen({ path: 'D' })
      await flushPromises()

      expect(mockProductStore.createProduct).toHaveBeenCalledWith({ name: '' })
      expect(wrapper.find('[data-testid="tutorial-prompt-text"]').text()).toContain(
        'prod-uuid-1',
      )
    })

    it('NEVER selects an existing ACTIVE product (audit F1 — products[0] is the active one)', async () => {
      // list_products orders is_active.desc: the user's REAL product is [0].
      mockProductStore.products = [
        { id: 'alpha-active', name: 'Alpha', description: 'Real product', is_active: true },
      ]
      const wrapper = mountScreen({ path: 'D' })
      await flushPromises()

      // A fresh draft is created instead; Alpha is never referenced or advanced.
      expect(mockProductStore.createProduct).toHaveBeenCalledWith({ name: '' })
      const text = wrapper.find('[data-testid="tutorial-prompt-text"]').text()
      expect(text).toContain('prod-uuid-1')
      expect(text).not.toContain('alpha-active')
      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(false)
      // The new draft is registered with the state machine.
      expect(wrapper.emitted('product-created')?.at(-1)).toEqual(['prod-uuid-1'])
    })

    it('adopts ONLY an empty-named inactive draft (a previous tutorial leftover)', async () => {
      mockProductStore.products = [
        { id: 'alpha-active', name: 'Alpha', description: 'Real product', is_active: true },
        { id: 'old-draft', name: '', description: '', is_active: false },
      ]
      const wrapper = mountScreen({ path: 'D' })
      await flushPromises()

      expect(mockProductStore.createProduct).not.toHaveBeenCalled()
      expect(wrapper.find('[data-testid="tutorial-prompt-text"]').text()).toContain('old-draft')
      expect(wrapper.emitted('product-created')?.at(-1)).toEqual(['old-draft'])
    })

    it('uses the threaded run-owned productId without creating or adopting', async () => {
      mockProductStore.products = [
        { id: 'alpha-active', name: 'Alpha', description: 'Real product', is_active: true },
      ]
      const wrapper = mountScreen({ path: 'D', productId: 'run-owned-1' })
      await flushPromises()

      expect(mockProductStore.createProduct).not.toHaveBeenCalled()
      expect(wrapper.find('[data-testid="tutorial-prompt-text"]').text()).toContain('run-owned-1')
    })

    it('renders the CE wording by default and the SaaS variant in SaaS mode', async () => {
      let wrapper = mountScreen({ path: 'D' })
      await flushPromises()
      expect(wrapper.text()).toContain('self-hosted Giljo HQ server')

      mockIsSaas = true
      wrapper = mountScreen({ path: 'D' })
      await flushPromises()
      expect(wrapper.text()).toContain('browser sign-in')
      expect(wrapper.text()).not.toContain('self-hosted Giljo HQ server')
    })

    it('poll ignores intermediate section writes and advances ONLY on the final consolidated-vision write', async () => {
      vi.useFakeTimers()
      const wrapper = mountScreen({ path: 'D' })
      await flushPromises()

      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(false)

      // Progressive fill, calls 1-4: card sections land, NO consolidated vision
      // yet — display-only, never navigation.
      mockProductStore.fetchProductById.mockImplementation(async () => ({
        id: 'prod-uuid-1',
        name: 'agent-named',
        description: 'Populated by the agent.',
        tech_stack: { programming_languages: 'Python' },
      }))
      await vi.advanceTimersByTimeAsync(10_000)
      await flushPromises()
      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(false)
      expect(wrapper.emitted('review')).toBeFalsy()

      // Call 5 (LAST): consolidated vision lands — the done-signal.
      mockProductStore.fetchProductById.mockImplementation(async () => ({
        id: 'prod-uuid-1',
        name: 'agent-named',
        description: 'Populated by the agent.',
        consolidated_vision_light: 'Light consolidated summary.',
      }))
      await vi.advanceTimersByTimeAsync(10_000)
      await flushPromises()

      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(true)

      await vi.advanceTimersByTimeAsync(1_500)
      expect(wrapper.emitted('review')).toBeTruthy()
    })

    it('treats an already-CONSOLIDATED run-owned product as done at mount (re-entry)', async () => {
      vi.useFakeTimers()
      mockProductStore.fetchProductById.mockImplementation(async () => ({
        id: 'run-owned-1',
        name: 'Named',
        description: 'Full card.',
        consolidated_vision_light: 'Light consolidated summary.',
      }))
      const wrapper = mountScreen({ path: 'D', productId: 'run-owned-1' })
      await flushPromises()

      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(true)
      await vi.advanceTimersByTimeAsync(1_500)
      expect(wrapper.emitted('review')).toBeTruthy()
    })

    it('a run-owned card with sections but NO consolidated vision does NOT auto-advance at mount', async () => {
      vi.useFakeTimers()
      mockProductStore.fetchProductById.mockImplementation(async () => ({
        id: 'run-owned-1',
        name: 'Named',
        description: 'Full card.',
      }))
      const wrapper = mountScreen({ path: 'D', productId: 'run-owned-1' })
      await flushPromises()

      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(false)
      expect(wrapper.emitted('review')).toBeFalsy()
    })

    it('does NOT treat vision_analysis_complete=false with empty fields as done', async () => {
      vi.useFakeTimers()
      const wrapper = mountScreen({ path: 'D' })
      await flushPromises()

      await vi.advanceTimersByTimeAsync(10_000)
      await flushPromises()

      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(false)
      expect(wrapper.emitted('review')).toBeFalsy()
    })

    it('marks done on the live window event once the seam confirms the consolidated vision', async () => {
      const wrapper = mountScreen({ path: 'D' })
      await flushPromises()

      mockProductStore.fetchProductById.mockImplementation(async () => ({
        id: 'prod-uuid-1',
        name: 'agent-named',
        description: 'Populated by the agent.',
        consolidated_vision_light: 'Light consolidated summary.',
      }))
      window.dispatchEvent(
        new CustomEvent('vision-analysis-complete', { detail: { product_id: 'prod-uuid-1' } }),
      )
      await flushPromises()

      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(true)
    })

    it('does NOT advance on an event for an intermediate section write (progressive-fill guard)', async () => {
      const wrapper = mountScreen({ path: 'D' })
      await flushPromises()

      // Calls 1-4 fire WS events too, but the card has no consolidated vision
      // yet — the done-signal seam (agentReportsDone) must veto the advance.
      mockProductStore.fetchProductById.mockImplementation(async () => ({
        id: 'prod-uuid-1',
        name: 'agent-named',
        description: 'Populated by the agent.',
        tech_stack: { programming_languages: 'Python' },
      }))
      window.dispatchEvent(
        new CustomEvent('vision-analysis-complete', { detail: { product_id: 'prod-uuid-1' } }),
      )
      await flushPromises()

      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(false)
    })

    it('ignores the event for a different product', async () => {
      const wrapper = mountScreen({ path: 'D' })
      await flushPromises()

      window.dispatchEvent(
        new CustomEvent('vision-analysis-complete', { detail: { product_id: 'other' } }),
      )
      await flushPromises()

      expect(wrapper.find('[data-testid="tutorial-agent-done"]').exists()).toBe(false)
    })
  })

  describe('path B', () => {
    it('creates no product and offers the upload hand-off', async () => {
      const wrapper = mountScreen({ path: 'B' })
      await flushPromises()

      expect(mockProductStore.createProduct).not.toHaveBeenCalled()
      const uploadBtn = wrapper.find('[data-testid="tutorial-b-upload"]')
      expect(uploadBtn.exists()).toBe(true)

      await uploadBtn.trigger('click')
      expect(wrapper.emitted('upload')).toBeTruthy()
    })

    it('renders the interview prompt with escape hatches', async () => {
      const wrapper = mountScreen({ path: 'B' })
      await flushPromises()

      const text = wrapper.find('[data-testid="tutorial-prompt-text"]').text()
      expect(text).toContain('ONE question at a time')
      expect(text).toContain('would you like me to propose one?')
    })
  })

  describe('copy button', () => {
    it('copies the rendered prompt and flips to Copied', async () => {
      const wrapper = mountScreen({ path: 'B' })
      await flushPromises()

      await wrapper.find('[data-testid="tutorial-copy-prompt"]').trigger('click')
      await flushPromises()

      expect(mockCopy).toHaveBeenCalledTimes(1)
      expect(mockCopy.mock.calls[0][0]).toContain('product-shaping partner')
      expect(wrapper.find('[data-testid="tutorial-copy-prompt"]').text()).toBe('Copied')
    })
  })
})
