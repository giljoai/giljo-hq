import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { learning_complete: true, learning_beat: 1 },
    updateSetupState: vi.fn(async (payload) => ({ ...payload })),
  }),
}))
vi.mock('@/services/api', () => ({ api: {}, default: {} }))

import TutorialOverlay from '@/components/tutorial/TutorialOverlay.vue'

const vuetify = createVuetify({ components, directives })
const STUBS = { Teleport: true, 'router-link': { template: '<a><slot /></a>' } }
const NOTICE = '[data-testid="tutorial-motion-notice"]'
const PLAY = '[data-testid="tutorial-play-animations"]'

const originalMatchMedia = window.matchMedia

function setReducedMotion(matches) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: matches && query.includes('prefers-reduced-motion'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
  }))
}

async function mountTour() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(TutorialOverlay, {
    props: { modelValue: true },
    global: { plugins: [vuetify, pinia], stubs: STUBS },
  })
  await flushPromises()
  return wrapper
}

const isStill = (wrapper) => wrapper.find('.tutorial-panel').classes().includes('tutorial--reduced')

describe('TutorialOverlay: Play animations', () => {
  afterEach(() => {
    window.matchMedia = originalMatchMedia
  })

  describe('on a device set to reduce motion', () => {
    beforeEach(() => setReducedMotion(true))

    it('shows still pictures and says why until the user asks', async () => {
      const wrapper = await mountTour()

      expect(isStill(wrapper)).toBe(true)
      expect(wrapper.find(NOTICE).text()).toContain('Animations are off on this device')
      expect(wrapper.find(PLAY).text()).toContain('Play animations')
    })

    it('starts the animations from the beginning and removes the bar on click', async () => {
      const wrapper = await mountTour()
      const stillBeat = wrapper.find('.beat').element

      await wrapper.find(PLAY).trigger('click')
      await flushPromises()

      expect(isStill(wrapper)).toBe(false)
      expect(wrapper.find(NOTICE).exists()).toBe(false)
      expect(wrapper.find('.beat').element).not.toBe(stillBeat)
    })

    it('keeps the animations playing on the next stop', async () => {
      const wrapper = await mountTour()
      await wrapper.find(PLAY).trigger('click')
      await wrapper.find('[data-testid="tutorial-next"]').trigger('click')
      await flushPromises()

      expect(isStill(wrapper)).toBe(false)
      expect(wrapper.find(NOTICE).exists()).toBe(false)
    })

    it('does not show the bar on the Get started stop, which has no animations', async () => {
      const wrapper = await mountTour()
      await wrapper.find('[data-testid="tutorial-rail-stop-6"]').trigger('click')
      await flushPromises()

      expect(wrapper.find(NOTICE).exists()).toBe(false)
    })
  })

  it('never shows the bar on a device with animations on', async () => {
    setReducedMotion(false)
    const wrapper = await mountTour()

    expect(isStill(wrapper)).toBe(false)
    expect(wrapper.find(NOTICE).exists()).toBe(false)
  })

  it('has no stylesheet rule that would keep the tour still after the click', () => {
    const source = readFileSync(resolve(__dirname, 'TutorialOverlay.vue'), 'utf8')

    expect(source).not.toMatch(/@media\s*\(prefers-reduced-motion/)
  })
})
