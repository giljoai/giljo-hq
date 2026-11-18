import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ push: vi.fn(), patch: vi.fn(), openTab: vi.fn(), fetchById: vi.fn(), del: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ meta: {}, query: {} }),
  useRouter: () => ({ push: h.push }),
}))
vi.mock('@/services/api', () => {
  const apiObj = { auth: { updateSetupState: (...a) => h.patch(...a) } }
  return { default: apiObj, api: apiObj }
})
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    openTab: (...a) => h.openTab(...a),
    fetchProductById: (...a) => h.fetchById(...a),
    deleteProduct: (...a) => h.del(...a),
  }),
}))

import StartProductDialog from '@/components/onboarding/StartProductDialog.vue'
import TutorialRouter from '@/components/tutorial/TutorialRouter.vue'
import TutorialRail from '@/components/tutorial/TutorialRail.vue'
import TutorialFooter from '@/components/tutorial/TutorialFooter.vue'
import TutorialPromptScreen from '@/components/tutorial/TutorialPromptScreen.vue'
import { useUserStore } from '@/stores/user'

function mountDialog(props = {}) {
  setActivePinia(createPinia())
  useUserStore().currentUser = { id: 'u-1' }
  return mount(StartProductDialog, {
    props: { modelValue: true, ...props },
    global: {
      stubs: {
        TutorialPromptScreen: true,
        TutorialUploadScreen: true,
        TutorialReviewScreen: true,
      },
    },
  })
}
const id = (w, t) => w.find(`[data-testid="${t}"]`)

describe('StartProductDialog', () => {
  beforeEach(() => {
    window.innerWidth = 1280
    Object.values(h).forEach((v) => v.mockReset())
    h.patch.mockResolvedValue({ data: {} })
    h.fetchById.mockResolvedValue(null)
  })

  it('shows the four ways to start, and none of the tour frame', () => {
    const w = mountDialog()
    expect(w.findComponent(TutorialRouter).exists()).toBe(true)
    for (const d of ['A', 'B', 'C', 'D']) expect(id(w, `tutorial-door-${d}`).exists()).toBe(true)
    expect(w.findComponent(TutorialRail).exists()).toBe(false)
    expect(w.findComponent(TutorialFooter).exists()).toBe(false)
    expect(id(w, 'tutorial-skip').exists()).toBe(false)
    expect(id(w, 'tutorial-overlay').exists()).toBe(false)
  })

  it('has its own header with a close control that closes it', async () => {
    const w = mountDialog()
    expect(id(w, 'start-product-dialog').exists()).toBe(true)
    await id(w, 'start-product-close').trigger('click')
    expect(w.emitted('update:modelValue')?.[0]).toEqual([false])
  })

  it('door D (existing code) goes to the prompt screen; Back returns to the doors', async () => {
    const w = mountDialog()
    await id(w, 'tutorial-door-D').trigger('click')
    expect(w.findComponent(TutorialPromptScreen).exists()).toBe(true)
    expect(w.findComponent(TutorialRouter).exists()).toBe(false)
    await id(w, 'start-product-back').trigger('click')
    expect(w.findComponent(TutorialRouter).exists()).toBe(true)
  })

  it('door C (fill it in myself) closes the dialog and opens the blank product form', async () => {
    const w = mountDialog()
    await id(w, 'tutorial-door-C').trigger('click')
    await flushPromises()
    expect(h.push).toHaveBeenCalledWith('/Products?create=blank')
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual([false])
  })

  it('opening it again starts at the doors', async () => {
    const w = mountDialog()
    await id(w, 'tutorial-door-D').trigger('click')
    await w.setProps({ modelValue: false })
    await w.setProps({ modelValue: true })
    expect(w.findComponent(TutorialRouter).exists()).toBe(true)
  })

  it('on a phone it fills the screen', () => {
    window.innerWidth = 420
    const w = mountDialog()
    expect(w.find('.v-dialog').attributes('fullscreen')).toBe('true')
  })

  it('on a desktop it does not', () => {
    const w = mountDialog()
    expect(w.find('.v-dialog').attributes('fullscreen')).not.toBe('true')
  })
})
