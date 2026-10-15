import { readFileSync } from 'fs'
import { resolve } from 'path'

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  settings: {
    getAgentSilenceThreshold: vi.fn(),
    updateAgentSilenceThreshold: vi.fn(),
    getAgentCheckinCadence: vi.fn(),
    updateAgentCheckinCadence: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({ default: apiMock, api: apiMock }))

import AgentTimingSettings from './AgentTimingSettings.vue'
import { withRealVuetify } from '../../../tests/helpers/realVuetify.js'

function resolveDefaults() {
  apiMock.settings.getAgentSilenceThreshold.mockResolvedValue({
    data: { agent_silence_threshold_minutes: 22 },
  })
  apiMock.settings.getAgentCheckinCadence.mockResolvedValue({
    data: { agent_checkin_cadence_minutes: 15 },
  })
  apiMock.settings.updateAgentSilenceThreshold.mockResolvedValue({
    data: { agent_silence_threshold_minutes: 22 },
  })
  apiMock.settings.updateAgentCheckinCadence.mockResolvedValue({
    data: { agent_checkin_cadence_minutes: 15 },
  })
}

async function mountIt() {
  const wrapper = mount(AgentTimingSettings)
  await flushPromises()
  return wrapper
}

describe('AgentTimingSettings (FE-9553, relocated from the Notifications tab)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    resolveDefaults()
  })

  it('loads both values from the server on mount', async () => {
    const wrapper = await mountIt()

    expect(apiMock.settings.getAgentSilenceThreshold).toHaveBeenCalledTimes(1)
    expect(apiMock.settings.getAgentCheckinCadence).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.silenceMinutes).toBe(22)
    expect(wrapper.vm.cadenceMinutes).toBe(15)
  })

  it('renders both inputs', async () => {
    const wrapper = await mountIt()

    expect(wrapper.find('[data-test="silence-threshold-input"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="checkin-cadence-input"]').exists()).toBe(true)
  })

  it('saves the threshold on change, with the value the user typed', async () => {
    const wrapper = await mountIt()

    wrapper.vm.silenceMinutes = 17
    await wrapper.vm.saveSilence()

    expect(apiMock.settings.updateAgentSilenceThreshold).toHaveBeenCalledWith(17)
  })

  it('saves the cadence on change, with the value the user typed', async () => {
    const wrapper = await mountIt()

    wrapper.vm.cadenceMinutes = 25
    await wrapper.vm.saveCadence()

    expect(apiMock.settings.updateAgentCheckinCadence).toHaveBeenCalledWith(25)
  })

  it('has NO edition gate -- it takes no mode dependency at all', () => {
    const source = readFileSync(resolve(__dirname, 'AgentTimingSettings.vue'), 'utf8')

    expect(source).toContain('silence-threshold-input')

    for (const modeSource of ['useGiljoMode', 'setupService', 'isCeModeValue', 'GILJO_MODE']) {
      expect(source).not.toContain(modeSource)
    }
  })

  describe('cases the view-level spec could not reach', () => {
    it('does NOT save a value the rules reject', async () => {
      const wrapper = await mountIt()

      wrapper.vm.silenceMinutes = 0
      await wrapper.vm.saveSilence()
      wrapper.vm.silenceMinutes = 5000
      await wrapper.vm.saveSilence()
      wrapper.vm.silenceMinutes = 12.5
      await wrapper.vm.saveSilence()

      expect(apiMock.settings.updateAgentSilenceThreshold).not.toHaveBeenCalled()
    })

    it('one failing load does not take the other down', async () => {
      apiMock.settings.getAgentSilenceThreshold.mockRejectedValueOnce(new Error('boom'))

      const wrapper = await mountIt()

      expect(wrapper.vm.cadenceMinutes).toBe(15)
      expect(wrapper.find('[data-test="agent-timing-error"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="silence-threshold-input"]').attributes('disabled')).toBeDefined()
    })

    it('a rejected save surfaces an error and says the server value is unchanged', async () => {
      apiMock.settings.updateAgentCheckinCadence.mockRejectedValueOnce(new Error('boom'))
      const wrapper = await mountIt()

      wrapper.vm.cadenceMinutes = 30
      await wrapper.vm.saveCadence()
      await flushPromises()

      expect(wrapper.find('[data-test="agent-timing-error"]').exists()).toBe(true)
    })
  })
})

let realVuetify

async function mountTyping() {
  realVuetify = await withRealVuetify(['VTextField', 'VField', 'VInput', 'VProgressLinear'])
  const wrapper = mount(AgentTimingSettings, {
    attachTo: document.body,
    global: { plugins: [realVuetify.plugin] },
  })
  await flushPromises()
  return wrapper
}

function fieldInput(wrapper, testId) {
  return wrapper.find(`[data-test="${testId}"] input`)
}

function isLoading(wrapper, testId) {
  return wrapper.find(`[data-test="${testId}"] .v-field--loading`).exists()
}

async function typeKeys(input, text) {
  let typed = ''
  const disabledSeen = []
  for (const ch of text) {
    typed += ch
    input.element.value = typed
    await input.trigger('input')
    disabledSeen.push(input.element.disabled)
    await flushPromises()
  }
  return disabledSeen
}

const FIELDS = [
  ['silence threshold', 'silence-threshold-input', 'updateAgentSilenceThreshold', 'silenceMinutes'],
  ['check-in cadence', 'checkin-cadence-input', 'updateAgentCheckinCadence', 'cadenceMinutes'],
]

describe.each(FIELDS)('FE-9776: the %s field takes a multi-digit value', (_label, testId, apiFn, vmKey) => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    resolveDefaults()
  })

  afterEach(() => {
    realVuetify?.restore()
    realVuetify = undefined
    document.body.innerHTML = ''
  })

  it('typing "3" then "0" ends at 30, never disables the input, and saves 30 exactly once on blur', async () => {
    const wrapper = await mountTyping()
    const input = fieldInput(wrapper, testId)

    const disabledSeen = await typeKeys(input, '30')

    expect(disabledSeen).toEqual([false, false])
    expect(apiMock.settings[apiFn]).not.toHaveBeenCalled()
    expect(wrapper.vm[vmKey]).toBe(30)

    await input.trigger('blur')
    await flushPromises()

    expect(apiMock.settings[apiFn]).toHaveBeenCalledTimes(1)
    expect(apiMock.settings[apiFn]).toHaveBeenCalledWith(30)
  })

  it('Enter commits, and the blur that follows does not save a second time', async () => {
    const wrapper = await mountTyping()
    const input = fieldInput(wrapper, testId)

    await typeKeys(input, '45')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    await input.trigger('blur')
    await flushPromises()

    expect(apiMock.settings[apiFn]).toHaveBeenCalledTimes(1)
    expect(apiMock.settings[apiFn]).toHaveBeenCalledWith(45)
  })

  it('stays enabled and focusable while its save is in flight', async () => {
    let release
    apiMock.settings[apiFn].mockReturnValueOnce(new Promise((r) => (release = r)))
    const wrapper = await mountTyping()
    const input = fieldInput(wrapper, testId)

    await typeKeys(input, '30')
    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.vm.$nextTick()

    expect(input.element.disabled).toBe(false)
    expect(isLoading(wrapper, testId)).toBe(true)

    release({ data: {} })
    await flushPromises()
    expect(isLoading(wrapper, testId)).toBe(false)
  })

  it('an out-of-range or fractional value saves nothing', async () => {
    const wrapper = await mountTyping()
    const input = fieldInput(wrapper, testId)

    for (const bad of ['0', '5000', '12.5', '']) {
      input.element.value = ''
      await typeKeys(input, bad)
      await input.trigger('blur')
      await input.trigger('keydown', { key: 'Enter' })
      await flushPromises()
    }

    expect(apiMock.settings[apiFn]).not.toHaveBeenCalled()
  })

  it('an out-of-range value shows the rule message', async () => {
    const wrapper = await mountTyping()
    const input = fieldInput(wrapper, testId)

    input.element.value = ''
    await typeKeys(input, '5000')
    await input.trigger('blur')
    await flushPromises()

    expect(wrapper.find(`[data-test="${testId}"]`).text()).toContain(
      'Must be between 1 and 1440 minutes',
    )
    expect(apiMock.settings[apiFn]).not.toHaveBeenCalled()
  })

  it('leaving the view with a typed value still focused saves it once', async () => {
    const wrapper = await mountTyping()
    const input = fieldInput(wrapper, testId)

    await typeKeys(input, '30')
    wrapper.unmount()
    await flushPromises()

    expect(apiMock.settings[apiFn]).toHaveBeenCalledTimes(1)
    expect(apiMock.settings[apiFn]).toHaveBeenCalledWith(30)
  })

  it('after a failed save, the next blur retries the same value', async () => {
    apiMock.settings[apiFn].mockRejectedValueOnce(new Error('boom'))
    const wrapper = await mountTyping()
    const input = fieldInput(wrapper, testId)

    await typeKeys(input, '30')
    await input.trigger('blur')
    await flushPromises()
    expect(wrapper.find('[data-test="agent-timing-error"]').exists()).toBe(true)

    await input.trigger('blur')
    await flushPromises()
    expect(apiMock.settings[apiFn]).toHaveBeenCalledTimes(2)
    expect(apiMock.settings[apiFn]).toHaveBeenLastCalledWith(30)
  })

  it('blur with the loaded value unchanged saves nothing', async () => {
    const wrapper = await mountTyping()
    const input = fieldInput(wrapper, testId)

    await input.trigger('blur')
    await flushPromises()

    expect(apiMock.settings[apiFn]).not.toHaveBeenCalled()
  })
})
