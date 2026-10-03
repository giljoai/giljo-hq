import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  settings: {
    getDatabase: vi.fn(),
    getAgentSilenceThreshold: vi.fn(),
    updateAgentSilenceThreshold: vi.fn(),
    getAgentCheckinCadence: vi.fn(),
    updateAgentCheckinCadence: vi.fn(),
  },
}))
vi.mock('@/services/api', () => ({ default: apiMock, api: apiMock }))

import DatabaseConnection from '@/components/DatabaseConnection.vue'
import AgentTimingSettings from '@/components/settings/AgentTimingSettings.vue'

const failure = (message) =>
  Object.assign(new Error('x'), { response: { status: 500, data: { message } } })

describe('a failed settings read is shown, and never rendered as defaults', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('database: the server values are shown, not localhost defaults', async () => {
    apiMock.settings.getDatabase.mockResolvedValue({
      data: { host: 'db.internal', port: 6543, name: 'giljo_live', user: 'giljo_owner', password_masked: '****' },
    })
    const wrapper = mount(DatabaseConnection, { props: { showTestButton: true } })
    await flushPromises()

    expect(wrapper.vm.dbConfig).toMatchObject({ host: 'db.internal', port: 6543, name: 'giljo_live', user: 'giljo_owner' })
  })

  it('database: a failed read shows the reason and disables the connection test', async () => {
    apiMock.settings.getDatabase.mockRejectedValue(failure('settings store is down'))
    const wrapper = mount(DatabaseConnection, { props: { showTestButton: true } })
    await flushPromises()

    const alert = wrapper.find('[data-test="db-load-error"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('settings store is down')
    expect(wrapper.vm.dbConfig.host).not.toBe('localhost')
    expect(wrapper.find('[data-test="test-connection-btn"]').attributes('disabled')).toBeDefined()
  })

  it('agent timing: a failed read shows the reason and holds the fields', async () => {
    apiMock.settings.getAgentSilenceThreshold.mockRejectedValue(failure('timing unavailable'))
    apiMock.settings.getAgentCheckinCadence.mockResolvedValue({ data: { agent_checkin_cadence_minutes: 15 } })
    const wrapper = mount(AgentTimingSettings)
    await flushPromises()

    const err = wrapper.find('[data-test="agent-timing-error"]')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('timing unavailable')
    expect(wrapper.find('[data-test="silence-threshold-input"]').attributes('disabled')).toBeDefined()
  })
})
