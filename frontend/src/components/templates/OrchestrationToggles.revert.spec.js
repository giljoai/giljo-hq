import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import OrchestrationToggles from '@/components/templates/OrchestrationToggles.vue'

const mockShowToast = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: (...a) => mockShowToast(...a) }),
}))

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

const SwitchStub = {
  name: 'VSwitch',
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template: `<input type="checkbox" v-bind="$attrs" :checked="modelValue" :disabled="disabled"
    @click="$emit('update:modelValue', !modelValue)" />`,
}

const serverError = () =>
  Object.assign(new Error('Request failed with status code 500'), {
    response: { status: 500, data: { error_code: 'HTTP_ERROR', message: 'boom save' } },
  })

function mountToggles() {
  return mount(OrchestrationToggles, {
    global: {
      plugins: [createTestingPinia({ createSpy: vi.fn })],
      stubs: {
        'v-switch': SwitchStub,
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
      },
    },
  })
}

const CASES = [
  { testid: 'closeout-mode-toggle', write: 'updateCloseoutMode', start: true, sent: 'autonomous' },
  { testid: 'headless-launch-toggle', write: 'updateHeadlessLaunch', start: false, sent: true },
]

describe('OrchestrationToggles: a failed save', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.settings.getGeneral.mockResolvedValue({ data: { settings: { closeout_mode: 'hitl' } } })
    api.settings.getHeadlessLaunch.mockResolvedValue({ data: { allow_headless_launch: false } })
    api.settings.updateCloseoutMode.mockRejectedValue(serverError())
    api.settings.updateHeadlessLaunch.mockRejectedValue(serverError())
  })

  it.each(CASES)('$testid shows its starting value again', async ({ testid, start }) => {
    const wrapper = mountToggles()
    await flushPromises()
    const shown = () =>
      wrapper.findAllComponents(SwitchStub).find((c) => c.attributes('data-testid') === testid).props('modelValue')
    expect(shown()).toBe(start)

    await wrapper.find(`[data-testid="${testid}"]`).trigger('click')
    await flushPromises()

    expect(shown()).toBe(start)
  })

  it.each(CASES)('$testid retry click asks for the same value again', async ({ testid, write, sent }) => {
    const wrapper = mountToggles()
    await flushPromises()
    const toggle = wrapper.find(`[data-testid="${testid}"]`)

    await toggle.trigger('click')
    await flushPromises()
    await toggle.trigger('click')
    await flushPromises()

    expect(api.settings[write].mock.calls).toEqual([[sent], [sent]])
  })

  it.each(CASES)("$testid error names the server's reason", async ({ testid }) => {
    const wrapper = mountToggles()
    await flushPromises()

    await wrapper.find(`[data-testid="${testid}"]`).trigger('click')
    await flushPromises()

    expect(mockShowToast).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('boom save') }),
    )
  })
})
