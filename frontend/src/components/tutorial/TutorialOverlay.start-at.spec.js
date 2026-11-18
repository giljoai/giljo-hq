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
    currentUser: { learning_complete: false, learning_beat: 2 },
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
const currentStop = (w) => w.find('[aria-current="step"]').text()

describe('TutorialOverlay: start at a stop', () => {
  beforeEach(() => vi.clearAllMocks())

  it('opens at the named stop whatever stop was stored', async () => {
    const w = mountClosed({ startAt: 6 })
    await w.setProps({ modelValue: true })
    await flushPromises()
    expect(currentStop(w)).toContain('Get started')
  })

  it('without startAt it still resumes at the stored stop', async () => {
    const w = mountClosed()
    await w.setProps({ modelValue: true })
    await flushPromises()
    expect(currentStop(w)).toContain('Product & crew')
  })

  it('opening at a stop does not mark the tour complete', async () => {
    const w = mountClosed({ startAt: 6 })
    await w.setProps({ modelValue: true })
    await flushPromises()
    const calls = h.updateSetupState.mock.calls.map((c) => c[0])
    expect(calls.some((p) => 'learning_complete' in p)).toBe(false)
  })
})
