import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/services/api', () => {
  const api = {
    settings: {
      getGeneral: vi.fn(),
      updateCloseoutMode: vi.fn(),
      getHeadlessLaunch: vi.fn(),
      updateHeadlessLaunch: vi.fn(),
    },
  }
  return { api, default: api }
})

import api from '@/services/api'
import OrchestrationToggles from '@/components/templates/OrchestrationToggles.vue'

const switchStub = {
  props: ['modelValue', 'disabled'],
  template: `<input type="checkbox" class="v-switch" v-bind="$attrs" :checked="modelValue" :disabled="disabled" />`,
}

describe('OrchestrationToggles: a failed read', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.settings.getGeneral.mockRejectedValue(
      Object.assign(new Error('x'), { response: { status: 500, data: { message: 'settings unavailable' } } }),
    )
    api.settings.getHeadlessLaunch.mockResolvedValue({ data: { allow_headless_launch: false } })
  })

  it('shows the reason and holds both switches', async () => {
    const wrapper = mount(OrchestrationToggles, {
      global: {
        plugins: [createTestingPinia({ createSpy: vi.fn })],
        stubs: { 'v-switch': switchStub, 'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' } },
      },
    })
    await flushPromises()

    const err = wrapper.find('[data-testid="orchestration-toggles-error"]')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('settings unavailable')
    expect(wrapper.find('[data-testid="closeout-mode-toggle"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="headless-launch-toggle"]').attributes('disabled')).toBeDefined()
  })
})
