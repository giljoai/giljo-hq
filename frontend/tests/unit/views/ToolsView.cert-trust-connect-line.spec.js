import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import configService from '@/services/configService'

// FE-9339 — the Certificate Trust line on Tools > Connect.
//
// The symptom is "my AI tool cannot connect", so the user goes to Connect. The fix
// lived only under Startup, which reads as "things I did on day one". Same modal,
// second entry point, CE only.

const modeState = vi.hoisted(() => ({ value: 'ce' }))
const apiMock = vi.hoisted(() => ({
  settings: {
    get: vi.fn(() =>
      Promise.resolve({ data: { notifications: { position: 'top-right', duration: 7 } } }),
    ),
    getAgentSilenceThreshold: vi.fn(() =>
      Promise.resolve({ data: { agent_silence_threshold_minutes: 10 } }),
    ),
    updateAgentSilenceThreshold: vi.fn(() => Promise.resolve({ data: {} })),
    getAgentCheckinCadence: vi.fn(() =>
      Promise.resolve({ data: { agent_checkin_cadence_minutes: 10 } }),
    ),
    updateAgentCheckinCadence: vi.fn(() => Promise.resolve({ data: {} })),
  },
}))

vi.mock('@/services/api', () => ({ default: apiMock, api: apiMock }))

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
  TemplateManager: { template: '<div />' },
  ApiKeyManager: { template: '<div />' },
  AgentExport: { template: '<div />' },
  ContextPriorityConfig: { template: '<div />' },
  ToolsConnectDirectory: { template: '<div />' },
  SerenaIntegrationCard: { template: '<div />' },
  GitIntegrationCard: { template: '<div />' },
  CertTrustModal: {
    props: ['modelValue'],
    template: '<div v-if="modelValue" data-test="cert-modal-open" />',
  },
}

describe('ToolsView — FE-9339 Certificate Trust entry point on Connect', () => {
  let router

  beforeEach(async () => {
    vi.clearAllMocks()
    localStorage.clear()
    modeState.value = 'ce'
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
      global: { plugins: [router], stubs: childStubs },
    })
    await flushPromises()
    return wrapper
  }

  it('CE: the Connect tab lists a Certificate Trust line in the integrations grid', async () => {
    modeState.value = 'ce'
    const wrapper = await mountView()

    const line = wrapper.find('[data-testid="cert-trust-line"]')
    expect(line.exists()).toBe(true)
    expect(line.text()).toContain('Certificate Trust')
    // Copy leads with the symptom, not the remedy.
    expect(line.text()).toContain('AI tool refusing to connect over HTTPS?')
  }, 15000)

  it('hosted (SaaS): the Certificate Trust line does not render at all', async () => {
    modeState.value = 'demo'
    const wrapper = await mountView()

    expect(wrapper.find('[data-testid="cert-trust-line"]').exists()).toBe(false)
  }, 15000)

  it('clicking it opens the existing CertTrustModal — WITHOUT first visiting the Startup tab', async () => {
    // The regression this guards: the modal used to be mounted inside the Startup
    // v-window-item, and VWindowItem renders its slot lazily (hasContent). Connect is
    // the default tab, so on a straight page load the modal was not in the DOM at all
    // and the click would have opened nothing.
    modeState.value = 'ce'
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="cert-modal-open"]').exists()).toBe(false)

    await wrapper.find('[data-testid="cert-trust-open"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-test="cert-modal-open"]').exists()).toBe(true)
  }, 15000)

  it('the Startup tab keeps its own Certificate Trust card, opening the same modal', async () => {
    modeState.value = 'ce'
    const wrapper = await mountView()

    await wrapper.find('[data-testid="startup-settings-tab"]').trigger('click')
    await flushPromises()

    const startupCards = wrapper.findAll('[data-test="startup-settings"] .startup-card')
    expect(startupCards.some((c) => c.text().includes('Certificate Trust'))).toBe(true)
  }, 15000)
})
