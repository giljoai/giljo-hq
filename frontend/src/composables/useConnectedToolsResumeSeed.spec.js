/**
 * useConnectedToolsResumeSeed.spec.js — FE-9569 detector 2, second cause.
 *
 * Extracted from SetupWizardOverlay.vue (CI guardrail 1's file-size budget)
 * to keep that file's line count flat -- tested here in isolation instead.
 * See the composable's own doc comment for the full story: a wizard resumed
 * directly onto Install (currentStep >= 2, e.g. from a persisted
 * setup_step_completed) never mounts SetupStep2Connect in that session, so
 * connectedTools stays empty forever without this seed.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { useConnectedToolsResumeSeed } from './useConnectedToolsResumeSeed'

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

beforeEach(() => {
  mockConnectedHarnesses = {}
  vi.clearAllMocks()
})

describe('useConnectedToolsResumeSeed', () => {
  it('does nothing while currentStep is below Install (2)', async () => {
    mockConnectedHarnesses = { 'claude-code': '2026-08-25T00:00:00Z' }
    const currentStep = ref(1)
    const step2Data = ref({})
    useConnectedToolsResumeSeed({
      currentStep: () => currentStep.value,
      selectedTools: () => ['claude_code'],
      step2Data,
    })
    await nextTick()
    expect(step2Data.value).toEqual({})
  })

  it('seeds connectedTools once currentStep reaches Install with nothing threaded yet', async () => {
    mockConnectedHarnesses = { 'claude-code': '2026-08-25T00:00:00Z' }
    const currentStep = ref(0)
    const step2Data = ref({})
    useConnectedToolsResumeSeed({
      currentStep: () => currentStep.value,
      selectedTools: () => ['claude_code'],
      step2Data,
    })
    currentStep.value = 2
    await nextTick()
    await Promise.resolve()
    await Promise.resolve()

    expect(step2Data.value.connectedTools).toEqual(['claude_code'])
  })

  it('never seeds a false positive when nothing is actually connected', async () => {
    mockConnectedHarnesses = {}
    const currentStep = ref(2)
    const step2Data = ref({})
    useConnectedToolsResumeSeed({
      currentStep: () => currentStep.value,
      selectedTools: () => ['claude_code'],
      step2Data,
    })
    await nextTick()
    await Promise.resolve()
    await Promise.resolve()

    expect(step2Data.value).toEqual({})
  })

  it('ignores a connected harness for a tool outside this run (not in selectedTools)', async () => {
    mockConnectedHarnesses = { opencode: '2026-08-25T00:00:00Z' }
    const currentStep = ref(2)
    const step2Data = ref({})
    useConnectedToolsResumeSeed({
      currentStep: () => currentStep.value,
      selectedTools: () => ['claude_code'],
      step2Data,
    })
    await nextTick()
    await Promise.resolve()
    await Promise.resolve()

    expect(step2Data.value).toEqual({})
  })

  it('never re-seeds once step2Data.connectedTools is already populated', async () => {
    mockConnectedHarnesses = { 'claude-code': '2026-08-25T00:00:00Z' }
    const currentStep = ref(2)
    const step2Data = ref({ connectedTools: ['codex_cli'] })
    useConnectedToolsResumeSeed({
      currentStep: () => currentStep.value,
      selectedTools: () => ['claude_code', 'codex_cli'],
      step2Data,
    })
    await nextTick()
    await Promise.resolve()
    await Promise.resolve()

    // Untouched -- the real live SetupStep2Connect data wins, never overwritten.
    expect(step2Data.value.connectedTools).toEqual(['codex_cli'])
  })
})
