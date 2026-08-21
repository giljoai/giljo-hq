import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import configService from '@/services/configService'

// FE-9339 follow-up — the "Don't show this again on this device" checkbox is only
// honoured if the host that mounted the modal listens for @continue. WelcomeView did;
// this door did not, so a user could tick "never" here and still be shown the modal
// by the setup wizard afterwards.

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

const certModalStub = {
  name: 'CertTrustModal',
  props: ['modelValue'],
  emits: ['update:modelValue', 'continue'],
  template: '<div v-if="modelValue" data-test="cert-modal-open" />',
}

const childStubs = {
  TemplateManager: { template: '<div />' },
  ApiKeyManager: { template: '<div />' },
  AgentExport: { template: '<div />' },
  ContextPriorityConfig: { template: '<div />' },
  ToolsConnectDirectory: { template: '<div />' },
  SerenaIntegrationCard: { template: '<div />' },
  GitIntegrationCard: { template: '<div />' },
  CertTrustModal: certModalStub,
}

describe('ToolsView — FE-9339 "don\'t show again" reaches storage', () => {
  let router

  beforeEach(async () => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
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

  async function openCertModal() {
    const { default: ToolsView } = await import('@/views/ToolsView.vue')
    const wrapper = mount(ToolsView, {
      global: { plugins: [router], stubs: childStubs },
    })
    await flushPromises()
    await wrapper.find('[data-testid="cert-trust-open"]').trigger('click')
    await nextTick()
    return wrapper
  }

  // localStorage is a spy in tests/setup.js, so assert on the write the way
  // WelcomeView.spec.js does rather than reading the value back.
  it('ticking the box and continuing persists cert_modal_never for this device', async () => {
    const wrapper = await openCertModal()

    // The modal emits the checkbox value on both Continue and Skip.
    wrapper.findComponent(certModalStub).vm.$emit('continue', true)
    await nextTick()

    expect(localStorage.setItem).toHaveBeenCalledWith('cert_modal_never', '1')
  }, 15000)

  it('continuing without ticking marks it dismissed for the session only', async () => {
    const wrapper = await openCertModal()

    wrapper.findComponent(certModalStub).vm.$emit('continue', false)
    await nextTick()

    expect(localStorage.setItem).not.toHaveBeenCalledWith('cert_modal_never', '1')
    expect(sessionStorage.getItem('cert_modal_dismissed')).toBe('1')
  }, 15000)
})
