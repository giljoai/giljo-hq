import { readFileSync } from 'fs'
import { resolve } from 'path'

import { describe, it, expect, vi, beforeEach } from 'vitest'
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
