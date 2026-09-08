/**
 * SetupWizardOverlay.resume-connected.spec.js — FE-9569 detector 2, SECOND
 * CAUSE confirmed live (not just inferred).
 *
 * WelcomeView.vue seeds the wizard's currentStep from the user's PERSISTED
 * setup_step_completed on every mount:
 *   setupStep.value = Math.min(setupStepCompleted.value, 3)
 * A user who reached Install in an earlier session (or simply reloads the
 * page while on Install) gets SetupWizardOverlay mounted DIRECTLY at
 * currentStep=2 -- SetupStep2Connect (index 1) never mounts in THIS
 * session at all. step2Data stays at its fresh `ref({})`, so
 * step2ConnectedTools is permanently `[]` and SetupStep3Commands's install
 * ticks can never flip, no matter how many times giljo_setup re-runs --
 * because the map they'd flip on was never seeded with a key.
 *
 * Pinned here as an automated regression test. Fix: on mount, if resuming at step >= 2 with
 * no connectedTools yet, seed it from the SAME durable credential-status
 * truth detector 1 already uses (GET /api/connect/credential-status).
 */
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

    // The REAL SetupStep3Commands is mounted (not stubbed) -- its own
    // toolStatus map must have a key for claude_code, so a later
    // setup:bootstrap_complete tick actually lands somewhere.
    expect(wrapper.find('.step-commands').exists()).toBe(true)
    const bootstrapHandler = wsHandlers['setup:bootstrap_complete']
    expect(bootstrapHandler).toBeTruthy()
    bootstrapHandler({})
    await flushPromises()

    expect(wrapper.findAll('.checklist-text--done')).toHaveLength(2)
  })

  it('does nothing when nothing is actually connected (no false seed)', async () => {
    mockConnectedHarnesses = {}
    const wrapper = await mountOverlay()

    const bootstrapHandler = wsHandlers['setup:bootstrap_complete']
    bootstrapHandler({})
    await flushPromises()

    // No connectedTools key exists at all -- the bootstrap event has
    // nowhere to land, same as the honest "nothing connected" state.
    expect(wrapper.findAll('.checklist-text--done')).toHaveLength(0)
  })

  it('does not run the resume-seed when landing on step 1 (Connect) normally', async () => {
    mockConnectedHarnesses = { 'claude-code': '2026-08-25T01:00:00Z' }
    const wrapper = await mountOverlay({ currentStep: 1 })
    // Step 2 (Connect) is stubbed in this spec -- SetupStep3Commands never
    // mounts, so there is nothing to seed yet. Just confirm no crash and
    // the stub rendered.
    expect(wrapper.find('.step2-stub').exists()).toBe(true)
  })
})
