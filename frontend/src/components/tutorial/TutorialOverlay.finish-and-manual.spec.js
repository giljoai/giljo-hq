import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  updateSetupState: vi.fn(async (payload) => ({ ...payload })),
  rows: new Map(),
  list: vi.fn(),
  get: vi.fn(),
  del: vi.fn(),
  activate: vi.fn(),
  createdId: null,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push }),
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: {},
    updateSetupState: h.updateSetupState,
  }),
}))

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      list: (...a) => h.list(...a),
      get: (...a) => h.get(...a),
      delete: (...a) => h.del(...a),
      activate: (...a) => h.activate(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({ fetchProjects: vi.fn().mockResolvedValue() }),
}))
vi.mock('@/stores/tasks', () => ({
  useTaskStore: () => ({ fetchTasks: vi.fn().mockResolvedValue() }),
}))
vi.mock('@/stores/commHubStore', () => ({
  useCommHubStore: () => ({ loadThreads: vi.fn().mockResolvedValue() }),
}))

import TutorialOverlay from '@/components/tutorial/TutorialOverlay.vue'
import { useProductStore } from '@/stores/products'

const vuetify = createVuetify({ components, directives })

const PRODUCT_A = { id: 'aaaaaaaa-0000-0000-0000-000000000001', name: 'Alpha', is_active: true }
const PRODUCT_B = { id: 'bbbbbbbb-0000-0000-0000-000000000002', name: 'Beta', is_active: true }
const TOUR = {
  id: 'cccccccc-0000-0000-0000-000000000003',
  name: 'Tour Product',
  description: 'Written by the agent',
  is_active: true,
}

const STUBS = {
  Teleport: true,
  'router-link': { template: '<a><slot /></a>' },
  TutorialPromptScreen: {
    template: `<div class="stub-prompt">
      <button class="stub-prompt-review" @click="$emit('review')">review</button>
      <button class="stub-prompt-manual" @click="$emit('manual')">manual</button>
    </div>`,
    emits: ['product-created', 'review', 'upload', 'manual'],
    mounted() {
      if (h.createdId) this.$emit('product-created', h.createdId)
    },
  },
  TutorialUploadScreen: { template: '<div class="stub-upload" />' },
  TutorialReviewScreen: {
    template: `<button class="stub-review-activate" @click="$emit('activated')">activate</button>`,
    emits: ['activated'],
  },
  TutorialDoneScreen: {
    template: `<button class="stub-done-close" @click="$emit('close')">Go to my dashboard</button>`,
    emits: ['close'],
  },
}

let pinia

function mountOverlay() {
  return mount(TutorialOverlay, {
    props: { modelValue: true },
    global: { plugins: [vuetify, pinia], stubs: STUBS, directives: { draggable: {} } },
  })
}

async function enterDoorD(wrapper) {
  await wrapper.find('[data-testid="tutorial-rail-stop-6"]').trigger('click')
  await wrapper.find('[data-testid="tutorial-door-D"]').trigger('click')
  await flushPromises()
}

describe('TutorialOverlay — FE-9795 tour exits', () => {
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
    h.createdId = TOUR.id
    h.rows = new Map([PRODUCT_A, PRODUCT_B, TOUR].map((p) => [p.id, { ...p }]))
    h.list.mockImplementation(() => Promise.resolve({ data: [...h.rows.values()] }))
    h.get.mockImplementation((id) => Promise.resolve({ data: h.rows.get(id) || null }))
    h.del.mockImplementation((id) => {
      h.rows.delete(id)
      return Promise.resolve({ data: null })
    })
    h.activate.mockResolvedValue({ data: null })

    store = useProductStore()
    store.$patch({
      products: [...h.rows.values()],
      currentProductId: PRODUCT_A.id,
      currentProduct: { ...PRODUCT_A },
    })
  })

  describe('finishing the tour selects the product it made', () => {
    it('"Go to my dashboard" makes the tour product current, not the previously selected one', async () => {
      const wrapper = mountOverlay()
      await enterDoorD(wrapper)
      await wrapper.find('.stub-prompt-review').trigger('click')
      await wrapper.find('.stub-review-activate').trigger('click')
      await wrapper.find('.stub-done-close').trigger('click')
      await flushPromises()

      expect(store.currentProductId).toBe(TOUR.id)
      expect(store.currentProduct?.id).toBe(TOUR.id)
      expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([false])
      expect(h.push).not.toHaveBeenCalled()
      expect(h.del).not.toHaveBeenCalled()
    })

    it('skipping after the door made a product leaves the current product alone', async () => {
      const wrapper = mountOverlay()
      await enterDoorD(wrapper)
      await wrapper.find('[data-testid="tutorial-skip"]').trigger('click')
      await flushPromises()

      expect(store.currentProductId).toBe(PRODUCT_A.id)
      expect(h.activate).not.toHaveBeenCalled()
    })
  })

  describe('"fill it in myself instead" from an agent door', () => {
    it('with no product made, opens the new-product form in blank mode', async () => {
      h.createdId = null
      const wrapper = mountOverlay()
      await enterDoorD(wrapper)
      await wrapper.find('.stub-prompt-manual').trigger('click')
      await flushPromises()

      expect(h.push).toHaveBeenCalledTimes(1)
      expect(h.push).toHaveBeenCalledWith('/Products?create=blank')
      expect(h.del).not.toHaveBeenCalled()
    })

    it('with an untouched draft, releases it and opens the blank form (no orphan, no duplicate)', async () => {
      h.rows.set(TOUR.id, { id: TOUR.id, name: '', is_active: true })
      const wrapper = mountOverlay()
      await enterDoorD(wrapper)
      await wrapper.find('.stub-prompt-manual').trigger('click')
      await flushPromises()

      expect(h.del).toHaveBeenCalledWith(TOUR.id)
      expect(h.push).toHaveBeenCalledTimes(1)
      expect(h.push).toHaveBeenCalledWith('/Products?create=blank')
    })

    it('with a draft that holds data, opens THAT product for editing instead of a second create', async () => {
      h.rows.set(TOUR.id, { id: TOUR.id, name: 'notes', vision_documents_count: 1, is_active: true })
      const wrapper = mountOverlay()
      await enterDoorD(wrapper)
      await wrapper.find('.stub-prompt-manual').trigger('click')
      await flushPromises()

      expect(h.del).not.toHaveBeenCalled()
      expect(h.push).toHaveBeenCalledTimes(1)
      expect(h.push).toHaveBeenCalledWith(`/Products?edit=${TOUR.id}`)
      expect(store.currentProductId).toBe(PRODUCT_A.id)
    })

    it('a double click leaves once', async () => {
      const wrapper = mountOverlay()
      await enterDoorD(wrapper)
      const btn = wrapper.find('.stub-prompt-manual')
      await btn.trigger('click')
      await btn.trigger('click')
      await flushPromises()

      expect(h.push).toHaveBeenCalledTimes(1)
    })
  })
})
