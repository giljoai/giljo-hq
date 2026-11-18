import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

const h = vi.hoisted(() => ({
  updateSetupState: vi.fn(async (payload) => ({ ...payload })),
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { learning_complete: true, learning_beat: 6, router_choice: 'A' },
    updateSetupState: h.updateSetupState,
  }),
}))
vi.mock('@/services/api', () => ({ api: {}, default: {} }))

import TutorialOverlay from '@/components/tutorial/TutorialOverlay.vue'

const vuetify = createVuetify({ components, directives })
const STUBS = { Teleport: true, 'router-link': { template: '<a><slot /></a>' } }

function mountClosed(props = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(TutorialOverlay, {
    props: { modelValue: false, ...props },
    global: { plugins: [vuetify, pinia], stubs: STUBS },
  })
}

const currentStop = (wrapper) => wrapper.find('[aria-current="step"]').text()

describe('TutorialOverlay: start over', () => {
  beforeEach(() => vi.clearAllMocks())

  it('opens at the first stop when asked to start over, whatever stop was stored', async () => {
    const wrapper = mountClosed({ startOver: true })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(currentStop(wrapper)).toContain('How it works')
    expect(wrapper.find('.beat-eyebrow').text()).toContain('How it works')
  })

  it('stores the new position so a reload does not return to the old stop', async () => {
    const wrapper = mountClosed({ startOver: true })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(h.updateSetupState).toHaveBeenCalledWith({ learning_beat: 1 })
  })

  it('still resumes at the stored stop when not asked to start over', async () => {
    const wrapper = mountClosed()
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(currentStop(wrapper)).toContain('Get started')
    expect(h.updateSetupState).not.toHaveBeenCalled()
  })
})
