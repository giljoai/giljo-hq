import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const wsHandlers = {}
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on(event, fn) {
      wsHandlers[event] = fn
      return () => { delete wsHandlers[event] }
    },
  }),
}))

let mockConnectedHarnesses = {}
vi.mock('@/services/api', () => ({
  default: {
    connect: {
      credentialStatus: vi.fn(() =>
        Promise.resolve({
          data: {
            has_valid_api_key: true,
            has_valid_oauth: false,
            has_expired_oauth: false,
            connected_harnesses: mockConnectedHarnesses,
          },
        }),
      ),
    },
  },
}))

vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn(() => Promise.resolve({ giljo_mode: 'ce' })) },
}))

async function mountOverlay(props = {}) {
  const SetupWizardOverlay = (await import('@/components/setup/SetupWizardOverlay.vue')).default
  const wrapper = mount(SetupWizardOverlay, {
    props: { modelValue: true, mode: 'setup', currentStep: 2, selectedTools: ['claude_code'], ...props },
    global: {
      stubs: {
        teleport: true,
        SetupStep2Connect: { template: '<div class="step2-stub" />' },
        SetupStep4Complete: { template: '<div class="step4-stub" />' },
        'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
        'v-icon': { template: '<i><slot /></i>' },
        'v-dialog': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'v-card-text': { template: '<div><slot /></div>' },
        'v-spacer': { template: '<span />' },
        Transition: { template: '<div><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('SetupWizardOverlay — resume directly onto Install with a real prior connection (FE-9569)', () => {
  it('seeds connectedTools from credential-status when resuming at step 2 with nothing threaded yet', async () => {
    mockConnectedHarnesses = { 'claude-code': '2026-08-25T01:00:00Z' }
    const wrapper = await mountOverlay()

    expect(wrapper.find('.step-commands').exists()).toBe(true)
    const bootstrapHandler = wsHandlers['setup:bootstrap_complete']
    expect(bootstrapHandler).toBeTruthy()
    bootstrapHandler({})
    await flushPromises()

    expect(wrapper.findAll('.checklist-text--done')).toHaveLength(1)
  })

  it('does nothing when nothing is actually connected (no false seed)', async () => {
    mockConnectedHarnesses = {}
    const wrapper = await mountOverlay()

    const bootstrapHandler = wsHandlers['setup:bootstrap_complete']
    bootstrapHandler({})
    await flushPromises()

    expect(wrapper.findAll('.checklist-text--done')).toHaveLength(0)
  })

  it('does not run the resume-seed when landing on step 1 (Connect) normally', async () => {
    mockConnectedHarnesses = { 'claude-code': '2026-08-25T01:00:00Z' }
    const wrapper = await mountOverlay({ currentStep: 1 })
    expect(wrapper.find('.step2-stub').exists()).toBe(true)
  })
})
