import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'

const apiMock = vi.hoisted(() => ({
  settings: {
    getExecutionModeDefault: vi.fn(),
    updateExecutionModeDefault: vi.fn(),
    getAgentSilenceThreshold: vi.fn(),
    updateAgentSilenceThreshold: vi.fn(),
    getAgentCheckinCadence: vi.fn(),
    updateAgentCheckinCadence: vi.fn(),
    getGeneral: vi.fn(),
    updateGeneral: vi.fn(),
    getHeadlessLaunch: vi.fn(),
    updateHeadlessLaunch: vi.fn(),
  },
}))
vi.mock('@/services/api', () => ({ default: apiMock, api: apiMock }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import AgentBehaviourView from '@/components/settings/AgentBehaviourView.vue'

function allDefaults() {
  apiMock.settings.getExecutionModeDefault.mockResolvedValue({
    data: { execution_mode_default: 'ask' },
  })
  apiMock.settings.getAgentSilenceThreshold.mockResolvedValue({
    data: { agent_silence_threshold_minutes: 10 },
  })
  apiMock.settings.getAgentCheckinCadence.mockResolvedValue({
    data: { agent_checkin_cadence_minutes: 10 },
  })
  apiMock.settings.getGeneral.mockResolvedValue({ data: { settings: { closeout_mode: 'hitl' } } })
  apiMock.settings.getHeadlessLaunch.mockResolvedValue({ data: { allow_headless_launch: true } })
}

const switchStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: `<input type="checkbox" class="v-switch" v-bind="$attrs" :checked="modelValue" @change="$emit('update:modelValue', $event.target.checked)" />`,
}

async function mountView() {
  const wrapper = mount(AgentBehaviourView, {
    global: {
      plugins: [createTestingPinia({ stubActions: false })],
      stubs: {
        'v-switch': switchStub,
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  allDefaults()
})

describe('FE-9643b — the view hosts all five settings', () => {
  it('renders five setting rows', async () => {
    const wrapper = await mountView()

    expect(wrapper.findAll('.setting-row')).toHaveLength(5)
  })

  it.each([
    ['execution mode', '[data-test="execution-mode-default-setting"]'],
    ['silence threshold', '[data-test="silence-threshold-input"]'],
    ['check-in cadence', '[data-test="checkin-cadence-input"]'],
    ['closeout approval', '[data-testid="closeout-mode-toggle"]'],
    ['headless self-advance', '[data-testid="headless-launch-toggle"]'],
  ])('keeps the %s control, with its existing test id', async (_name, selector) => {
    const wrapper = await mountView()

    expect(wrapper.find(selector).exists()).toBe(true)
  })

  it('orders the rows as the record specifies', async () => {
    const wrapper = await mountView()

    const names = wrapper.findAll('.setting-row-name').map((n) => n.text().trim())
    const expected = [
      'Execution mode when staging a project',
      'Silence threshold',
      'Check-in cadence',
      'Require approval before closeout',
      'Allow headless CLI self-advance',
    ]
    expect(names).toHaveLength(expected.length)
    names.forEach((text, i) => expect(text.startsWith(expected[i])).toBe(true))
  })

  it('says how changes are saved, and offers no Save button', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('Changes save as you make them')
    expect(wrapper.text()).toContain('How agents behave for this account')
    const labels = wrapper.findAll('button').map((b) => b.text())
    expect(labels.some((t) => /^save$/i.test(t.trim()))).toBe(false)
  })
})
