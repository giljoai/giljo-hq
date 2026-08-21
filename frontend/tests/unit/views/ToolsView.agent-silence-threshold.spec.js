import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import configService from '@/services/configService'

const modeState = vi.hoisted(() => ({ value: 'ce' }))
const apiMock = vi.hoisted(() => ({
  settings: {
    get: vi.fn(() =>
      Promise.resolve({
        data: {
          notifications: {
            position: 'top-right',
            duration: 7,
            agent_silence_threshold_minutes: 99,
          },
        },
      }),
    ),
    getAgentSilenceThreshold: vi.fn(() =>
      Promise.resolve({ data: { agent_silence_threshold_minutes: 22 } }),
    ),
    updateAgentSilenceThreshold: vi.fn(() =>
      Promise.resolve({ data: { agent_silence_threshold_minutes: 22 } }),
    ),
    // FE-9296b: account-level check-in cadence, hosted like the threshold above.
    getAgentCheckinCadence: vi.fn(() =>
      Promise.resolve({ data: { agent_checkin_cadence_minutes: 15 } }),
    ),
    updateAgentCheckinCadence: vi.fn(() =>
      Promise.resolve({ data: { agent_checkin_cadence_minutes: 15 } }),
    ),
  },
}))

vi.mock('@/services/api', () => ({
  default: apiMock,
  api: apiMock,
}))

vi.mock('@/services/setupService', () => ({
  default: {
    checkEnhancedStatus: vi.fn(() => Promise.resolve({ mode: modeState.value })),
    getSerenaStatus: vi.fn(() => Promise.resolve({ enabled: false })),
    getGitSettings: vi.fn(() => Promise.resolve({ enabled: false })),
    toggleSerena: vi.fn(() => Promise.resolve({ success: true, enabled: true })),
    toggleGit: vi.fn(() => Promise.resolve({ success: true, enabled: true })),
  },
}))

const childStubs = {
  TemplateManager: { template: '<div data-test="template-manager" />' },
  ApiKeyManager: { template: '<div data-test="api-key-manager" />' },
  AgentExport: { template: '<div data-test="agent-export" />' },
  ContextPriorityConfig: { template: '<div data-test="context-priority" />' },
  McpIntegrationCard: { template: '<div data-test="mcp-card" />' },
  SerenaIntegrationCard: { template: '<div data-test="serena-card" />' },
  GitIntegrationCard: { template: '<div data-test="git-card" />' },
  CertTrustModal: { template: '<div data-test="cert-modal" />' },
}

describe('ToolsView agent silence threshold settings', () => {
  let router

  beforeEach(async () => {
    vi.clearAllMocks()
    localStorage.clear()
    modeState.value = 'ce'
    // FE-6055: getGiljoMode() now returns 'unknown' (not 'ce') without a real
    // config. The settings store CE-gates its server load on a confirmed 'ce',
    // so seed a confirmed-CE config for this CE-mode suite.
    configService.config = { giljo_mode: 'ce', mode: 'server', api: {} }
    setActivePinia(createPinia())
    router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', name: 'Tools', component: { template: '<div />' } }],
    })
    await router.push('/')
    await router.isReady()
  })

  async function mountView() {
    const { default: ToolsView } = await import('@/views/ToolsView.vue')
    const wrapper = mount(ToolsView, {
      global: {
        plugins: [router],
        stubs: childStubs,
      },
    })
    await flushPromises()
    return wrapper
  }

  it('CE mode loads and saves the threshold through the system setting API', async () => {
    modeState.value = 'ce'
    const wrapper = await mountView()

    expect(apiMock.settings.getAgentSilenceThreshold).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-test="agent-monitoring-settings"]').exists()).toBe(true)
    expect(wrapper.vm.agentSilenceThresholdMinutes).toBe(22)

    wrapper.vm.agentSilenceThresholdMinutes = 17
    await wrapper.vm.saveNotificationSettings()

    // FE-9000d: notifications are browser-only now -- no server-sync call.
    // Persistence is via localStorage (verified across-reload in tests/unit/stores/settings.spec.js).
    const lastSave = JSON.parse(window.localStorage.setItem.mock.calls.at(-1)[1])
    expect(lastSave.notifications).toEqual({ position: 'top-right', duration: 7 })
    expect(apiMock.settings.updateAgentSilenceThreshold).toHaveBeenCalledWith(17)
    // load-sensitive: the dynamic import + mount in mountView() can exceed vitest's 5s
    // default when this spec runs alongside the two -n6 pytest jobs on a busy CI runner.
  }, 15000)

  it('loads and saves the check-in cadence beside the threshold (FE-9296b)', async () => {
    modeState.value = 'ce'
    const wrapper = await mountView()

    expect(apiMock.settings.getAgentCheckinCadence).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-test="checkin-cadence-input"]').exists()).toBe(true)
    expect(wrapper.vm.agentCheckinCadenceMinutes).toBe(15)

    wrapper.vm.agentCheckinCadenceMinutes = 25
    await wrapper.vm.saveNotificationSettings()

    expect(apiMock.settings.updateAgentCheckinCadence).toHaveBeenCalledWith(25)
  }, 15000)

  it('hosted (SaaS) mode shows the threshold and saves it as a per-tenant override (FE-9241)', async () => {
    modeState.value = 'demo'
    const wrapper = await mountView()

    expect(apiMock.settings.getAgentSilenceThreshold).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-test="agent-monitoring-settings"]').exists()).toBe(true)
    expect(wrapper.vm.agentSilenceThresholdMinutes).toBe(22)

    wrapper.vm.agentSilenceThresholdMinutes = 17
    await wrapper.vm.saveNotificationSettings()

    // FE-9000d: notifications are browser-only -- no server-sync call for those.
    // FE-9241: the silence threshold DOES sync to the server in hosted mode now
    // (it writes this tenant's own override, not the deployment-wide default).
    const lastSave = JSON.parse(window.localStorage.setItem.mock.calls.at(-1)[1])
    expect(lastSave.notifications).toEqual({ position: 'top-right', duration: 7 })
    expect(apiMock.settings.updateAgentSilenceThreshold).toHaveBeenCalledWith(17)
  }, 15000)
})
