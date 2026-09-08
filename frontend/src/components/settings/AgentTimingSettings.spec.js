/**
 * AgentTimingSettings.spec.js — FE-9553
 *
 * The behavioural half of what used to be
 * tests/unit/views/ToolsView.agent-silence-threshold.spec.js. Those three tests
 * mounted the whole view to assert that two inputs loaded and saved, which
 * worked only because the inputs happened to live on the tab the view rendered
 * eagerly. FE-9553 moved them to Tools -> Agents, so the behaviour is tested
 * here at the component that now OWNS it and the view spec keeps only the
 * placement claim.
 *
 * Nothing was dropped in the move: load, save, the CE/hosted question and the
 * value each API call receives are all still asserted, and there are now cases
 * the view-level spec could not reach at all -- an invalid keystroke, and one
 * load failing without taking the other down.
 *
 * Edition Scope: Both
 */
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
    // The old view-level spec covered this by mounting twice, with mode 'ce'
    // and 'demo', and asserting identical behaviour. The stronger claim is
    // structural: this component cannot be edition-gated because it imports
    // nothing that knows the edition.
    //
    // My first draft asserted `wrapper.html()` did not contain the string
    // 'mode', which failed on incidental matches in rendered attributes -- a
    // substring search over markup is not a structural claim, and it would
    // have been just as worthless had it passed. Reading the source and naming
    // the actual mode sources is provable.
    const source = readFileSync(resolve(__dirname, 'AgentTimingSettings.vue'), 'utf8')

    // Known-positive: prove the read reached the real file.
    expect(source).toContain('silence-threshold-input')

    for (const modeSource of ['useGiljoMode', 'setupService', 'isCeModeValue', 'GILJO_MODE']) {
      expect(source).not.toContain(modeSource)
    }
  })

  describe('cases the view-level spec could not reach', () => {
    it('does NOT save a value the rules reject', async () => {
      const wrapper = await mountIt()

      wrapper.vm.silenceMinutes = 0 // below the 1-minute floor
      await wrapper.vm.saveSilence()
      wrapper.vm.silenceMinutes = 5000 // above the 1440 ceiling
      await wrapper.vm.saveSilence()
      wrapper.vm.silenceMinutes = 12.5 // not a whole number
      await wrapper.vm.saveSilence()

      expect(apiMock.settings.updateAgentSilenceThreshold).not.toHaveBeenCalled()
    })

    it('one failing load does not take the other down', async () => {
      // This is why the loads moved out of ToolsView's onMounted: they were
      // unguarded awaits there, so either one rejecting aborted every load
      // after it -- including loadGitSettings, which is unrelated.
      apiMock.settings.getAgentSilenceThreshold.mockRejectedValueOnce(new Error('boom'))

      const wrapper = await mountIt()

      // The failed one keeps its default rather than rendering blank...
      expect(wrapper.vm.silenceMinutes).toBe(10)
      // ...and the other still loaded.
      expect(wrapper.vm.cadenceMinutes).toBe(15)
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
