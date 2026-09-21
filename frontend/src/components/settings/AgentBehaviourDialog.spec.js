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

import AgentBehaviourDialog from '@/components/settings/AgentBehaviourDialog.vue'

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

async function mountDialog(props = {}) {
  const wrapper = mount(AgentBehaviourDialog, {
    props: { modelValue: true, ...props },
    global: {
      plugins: [createTestingPinia({ stubActions: false })],
      stubs: {
        'v-dialog': { template: '<div class="v-dialog"><slot /></div>' },
        'v-switch': switchStub,
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        Teleport: true,
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

describe('FE-9616 — the dialog hosts all five settings', () => {
  it('renders five setting rows', async () => {
    const wrapper = await mountDialog()

    expect(wrapper.findAll('.setting-row')).toHaveLength(5)
  })

  it.each([
    ['execution mode', '[data-test="execution-mode-default-setting"]'],
    ['silence threshold', '[data-test="silence-threshold-input"]'],
    ['check-in cadence', '[data-test="checkin-cadence-input"]'],
    ['closeout approval', '[data-testid="closeout-mode-toggle"]'],
    ['headless self-advance', '[data-testid="headless-launch-toggle"]'],
  ])('keeps the %s control, with its existing test id', async (_name, selector) => {
    const wrapper = await mountDialog()

    expect(wrapper.find(selector).exists()).toBe(true)
  })

  it('orders the rows as the record specifies', async () => {
    const wrapper = await mountDialog()

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

    expect(wrapper.findAll('.setting-row-help').map((h) => h.text().trim())).toEqual([
      'Ask every time, or always use one mode.',
      'Marked silent after this long with no word.',
      'How often a waiting agent looks for work.',
      'A project waits for your OK before it closes.',
      'Your coding agent may skip the Implement click.',
    ])
  })

  it('says how changes are saved, and offers no Save button', async () => {
    const wrapper = await mountDialog()

    expect(wrapper.text()).toContain('Changes save as you make them.')
    expect(wrapper.text()).toContain('How agents behave for this account.')
    const labels = wrapper.findAll('button').map((b) => b.text())
    expect(labels.some((t) => /save/i.test(t))).toBe(false)
  })

  it('closes on Close without touching any setting', async () => {
    const wrapper = await mountDialog()

    await wrapper.find('[data-test="agent-behaviour-close"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([false])
    expect(apiMock.settings.updateExecutionModeDefault).not.toHaveBeenCalled()
    expect(apiMock.settings.updateGeneral).not.toHaveBeenCalled()
  })
})

describe('FE-9616 — the changed-from-default count', () => {
  it('is zero when every setting holds its shipped default', async () => {
    const wrapper = await mountDialog()

    expect(wrapper.emitted('update:changedCount')?.at(-1)).toEqual([0])
  })

  it('counts each setting that differs', async () => {
    allDefaults()
    apiMock.settings.getAgentSilenceThreshold.mockResolvedValue({
      data: { agent_silence_threshold_minutes: 45 },
    })
    apiMock.settings.getHeadlessLaunch.mockResolvedValue({
      data: { allow_headless_launch: false },
    })

    const wrapper = await mountDialog()

    expect(wrapper.emitted('update:changedCount')?.at(-1)).toEqual([2])
  })

  it('treats a failed read as unchanged rather than as a difference', async () => {
    allDefaults()
    apiMock.settings.getGeneral.mockRejectedValue(new Error('down'))
    apiMock.settings.getExecutionModeDefault.mockResolvedValue({
      data: { execution_mode_default: 'subagent' },
    })

    const wrapper = await mountDialog()

    expect(wrapper.emitted('update:changedCount')?.at(-1)).toEqual([1])
  })

  it('re-reads when the dialog closes', async () => {
    const wrapper = await mountDialog()
    expect(wrapper.emitted('update:changedCount')?.at(-1)).toEqual([0])

    apiMock.settings.getAgentCheckinCadence.mockResolvedValue({
      data: { agent_checkin_cadence_minutes: 30 },
    })
    await wrapper.setProps({ modelValue: false })
    await flushPromises()

    expect(wrapper.emitted('update:changedCount')?.at(-1)).toEqual([1])
  })
})
