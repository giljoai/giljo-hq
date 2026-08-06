/**
 * Unit tests for TutorialOverlay (FE-9200) — the shell: beats render + advance,
 * footer labels, router doors wiring (C side effects), skip persistence, and
 * reduced motion (final frames instead of animations), per CODE_GUIDANCE §7.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

const mockUpdateSetupState = vi.fn(async (payload) => ({ ...payload }))
let mockCurrentUser = {}

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    get currentUser() {
      return mockCurrentUser
    },
    updateSetupState: mockUpdateSetupState,
  }),
}))

const mockPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

// Product store — reached only through the abandoned-draft exit hatch (fix 4);
// the sub-screens that normally create products are stubbed below.
const mockFetchProductById = vi.fn(async () => ({ name: '', is_active: false }))
const mockDeleteProduct = vi.fn(async () => {})
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: mockFetchProductById,
    deleteProduct: mockDeleteProduct,
  }),
}))

import TutorialOverlay from '@/components/tutorial/TutorialOverlay.vue'
import BaseDialog from '@/components/common/BaseDialog.vue'

const vuetify = createVuetify({ components, directives })

// The four router sub-screens have their own specs; stub them here so the
// shell test does not exercise product-store side effects.
const SUBSCREEN_STUBS = {
  Teleport: true,
  // Beats carry /guide read-more links; no real router in this shell test.
  // Attrs (target/rel — fix 1) fall through to the stub's root <a>.
  'router-link': { template: '<a><slot /></a>' },
  // The prompt stub mimics the real screen's silent pre-create so the shell
  // test can exercise the run-owned-draft exit hatch (fix 4).
  TutorialPromptScreen: {
    template: '<div class="stub-prompt">prompt stub</div>',
    emits: ['product-created', 'review', 'upload'],
    mounted() {
      this.$emit('product-created', 'draft-1')
    },
  },
  TutorialUploadScreen: { template: '<div class="stub-upload">upload stub</div>' },
  TutorialReviewScreen: { template: '<div class="stub-review">review stub</div>' },
  TutorialDoneScreen: { template: '<div class="stub-done">done stub</div>' },
}

function mountOverlay(props = {}) {
  return mount(TutorialOverlay, {
    props: { modelValue: true, ...props },
    global: {
      plugins: [vuetify],
      stubs: SUBSCREEN_STUBS,
      // BaseDialog's v-draggable is app-registered (DecisionModal.spec idiom).
      directives: { draggable: {} },
    },
  })
}

describe('TutorialOverlay', () => {
  beforeEach(() => {
    mockCurrentUser = {}
    mockUpdateSetupState.mockClear()
    mockPush.mockClear()
    mockFetchProductById.mockClear()
    mockDeleteProduct.mockClear()
    window.localStorage.setItem.mockClear()
    window.matchMedia.mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
  })

  it('renders nothing when closed', () => {
    const wrapper = mountOverlay({ modelValue: false })
    expect(wrapper.find('[data-testid="tutorial-overlay"]').exists()).toBe(false)
  })

  it('opens on Beat 1 with the approved copy', () => {
    const wrapper = mountOverlay()
    // BE-9281: rebranded GiljoAI -> Giljo HQ in Beat 1 customer-facing copy.
    expect(wrapper.text()).toContain('Your tools do the thinking. Giljo HQ keeps the thread.')
    expect(wrapper.find('[data-testid="tutorial-rail-stop-1"]').classes()).toContain(
      'rail-stop--active',
    )
  })

  it('Next advances through beats and the rail follows', async () => {
    const wrapper = mountOverlay()
    await wrapper.find('[data-testid="tutorial-next"]').trigger('click')

    expect(wrapper.text()).toContain('Define your product once. Brief the whole crew.')
    expect(wrapper.find('[data-testid="tutorial-rail-stop-2"]').classes()).toContain(
      'rail-stop--active',
    )
    expect(wrapper.find('[data-testid="tutorial-rail-stop-1"]').classes()).toContain(
      'rail-stop--done',
    )
  })

  it('beat 5 relabels Next to "Choose your start" and beat 6 shows the four doors', async () => {
    const wrapper = mountOverlay()
    for (let i = 0; i < 4; i++) {
      await wrapper.find('[data-testid="tutorial-next"]').trigger('click')
    }
    expect(wrapper.find('[data-testid="tutorial-next"]').text()).toContain('Choose your start')

    await wrapper.find('[data-testid="tutorial-next"]').trigger('click')
    expect(wrapper.find('[data-testid="tutorial-next"]').exists()).toBe(false)
    for (const door of ['D', 'B', 'A', 'C']) {
      expect(wrapper.find(`[data-testid="tutorial-door-${door}"]`).exists()).toBe(true)
    }
  })

  it('rail click jumps straight to a beat', async () => {
    const wrapper = mountOverlay()
    await wrapper.find('[data-testid="tutorial-rail-stop-4"]').trigger('click')
    expect(wrapper.text()).toContain('Every project makes the next one smarter.')
  })

  it('doors D and B open the prompt screen; A opens the upload screen', async () => {
    for (const [door, stub] of [
      ['D', '.stub-prompt'],
      ['B', '.stub-prompt'],
      ['A', '.stub-upload'],
    ]) {
      const wrapper = mountOverlay()
      await wrapper.find('[data-testid="tutorial-rail-stop-6"]').trigger('click')
      await wrapper.find(`[data-testid="tutorial-door-${door}"]`).trigger('click')
      expect(wrapper.find(stub).exists()).toBe(true)
    }
  })

  describe('door C confirmation (walkthrough fix 3)', () => {
    async function openDoorC(wrapper) {
      await wrapper.find('[data-testid="tutorial-rail-stop-6"]').trigger('click')
      await wrapper.find('[data-testid="tutorial-door-C"]').trigger('click')
    }

    async function clickDialogButton(wrapper, label) {
      const btn = wrapper.findAll('button').find((b) => b.text().includes(label))
      expect(btn, `dialog button "${label}" should render`).toBeTruthy()
      await btn.trigger('click')
    }

    it('shows the confirmation dialog instead of leaving immediately', async () => {
      const wrapper = mountOverlay()
      await openDoorC(wrapper)

      expect(wrapper.find('[data-testid="tutorial-doorc-confirm-text"]').text()).toContain(
        'ready to fill it in yourself?',
      )
      // Nothing has left the tutorial yet.
      expect(mockPush).not.toHaveBeenCalled()
      expect(mockUpdateSetupState).not.toHaveBeenCalledWith({ learning_complete: true })
      expect(wrapper.emitted('update:modelValue')).toBeFalsy()
    })

    it('cancel returns to the router with the doors still up', async () => {
      const wrapper = mountOverlay()
      await openDoorC(wrapper)
      await clickDialogButton(wrapper, 'Cancel')

      // The booted v-dialog keeps its content in the DOM during/after the
      // leave transition — the component contract (v-model driven false) is
      // the reliable "dialog closed" signal in jsdom.
      expect(wrapper.findComponent(BaseDialog).props('modelValue')).toBe(false)
      expect(wrapper.find('[data-testid="tutorial-door-C"]').exists()).toBe(true)
      expect(mockPush).not.toHaveBeenCalled()
      expect(mockUpdateSetupState).not.toHaveBeenCalledWith({ learning_complete: true })
    })

    it('confirm arms the breadcrumb, finishes the tutorial, and opens the ProductForm', async () => {
      const wrapper = mountOverlay()
      await openDoorC(wrapper)
      await clickDialogButton(wrapper, 'Open the product form')

      expect(window.localStorage.setItem).toHaveBeenCalledWith(
        'giljo_tutorial_activate_breadcrumb',
        '1',
      )
      expect(mockUpdateSetupState).toHaveBeenCalledWith({ learning_complete: true })
      expect(mockPush).toHaveBeenCalledWith('/Products?create=true')
      expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([false])
      expect(wrapper.emitted('dismiss')).toBeTruthy()
    })
  })

  it('read-more guide links open in a new tab (walkthrough fix 1)', async () => {
    const wrapper = mountOverlay()
    for (let beat = 1; beat <= 4; beat++) {
      const link = wrapper.find('.beat-readmore')
      expect(link.exists(), `beat ${beat} read-more link`).toBe(true)
      expect(link.attributes('target'), `beat ${beat} target`).toBe('_blank')
      expect(link.attributes('rel'), `beat ${beat} rel`).toBe('noopener')
      await wrapper.find('[data-testid="tutorial-next"]').trigger('click')
    }
  })

  describe('abandoned-draft exit hatch wiring (walkthrough fix 4)', () => {
    it('skip after the door-D pre-create deletes the untouched draft', async () => {
      const wrapper = mountOverlay()
      await wrapper.find('[data-testid="tutorial-rail-stop-6"]').trigger('click')
      // The prompt stub emits product-created('draft-1') on mount (the real
      // screen's silent pre-create).
      await wrapper.find('[data-testid="tutorial-door-D"]').trigger('click')
      await wrapper.find('[data-testid="tutorial-skip"]').trigger('click')

      await vi.waitFor(() => expect(mockDeleteProduct).toHaveBeenCalledWith('draft-1'))
      expect(mockFetchProductById).toHaveBeenCalledWith('draft-1')
    })

    it('skip without a run-owned product never touches the product store', async () => {
      const wrapper = mountOverlay()
      await wrapper.find('[data-testid="tutorial-skip"]').trigger('click')
      await wrapper.vm.$nextTick()

      expect(mockFetchProductById).not.toHaveBeenCalled()
      expect(mockDeleteProduct).not.toHaveBeenCalled()
    })
  })

  it('skip persists learning_complete and closes (always visible)', async () => {
    const wrapper = mountOverlay()
    const skip = wrapper.find('[data-testid="tutorial-skip"]')
    expect(skip.text()).toContain("Skip — I'll explore on my own")

    await skip.trigger('click')

    expect(mockUpdateSetupState).toHaveBeenCalledWith({ learning_complete: true })
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([false])
    expect(wrapper.emitted('dismiss')).toBeTruthy()
  })

  it('replay control is visible on beats and re-mounts the current beat', async () => {
    const wrapper = mountOverlay()
    const replay = wrapper.find('[data-testid="tutorial-replay"]')
    expect(replay.exists()).toBe(true)

    const beatBefore = wrapper.find('.gj-anim').element
    await replay.trigger('click')
    const beatAfter = wrapper.find('.gj-anim').element
    expect(beatAfter).not.toBe(beatBefore)
  })

  it('resumes at a persisted beat (stale beat=6 lands on the router, not a crash)', () => {
    mockCurrentUser = { learning_beat: 6 }
    const wrapper = mountOverlay()
    expect(wrapper.find('[data-testid="tutorial-door-D"]').exists()).toBe(true)
  })

  describe('reduced motion', () => {
    it('applies the tutorial--reduced gate when the user prefers reduced motion', () => {
      window.matchMedia.mockImplementation((query) => ({
        matches: query === '(prefers-reduced-motion: reduce)',
        media: query,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }))

      const wrapper = mountOverlay()
      expect(wrapper.find('.tutorial-panel').classes()).toContain('tutorial--reduced')
      // Final frames stay visible: the beat content still renders.
      expect(wrapper.text()).toContain('Your tools do the thinking. Giljo HQ keeps the thread.')
    })

    it('omits the gate otherwise', () => {
      const wrapper = mountOverlay()
      expect(wrapper.find('.tutorial-panel').classes()).not.toContain('tutorial--reduced')
    })
  })
})
