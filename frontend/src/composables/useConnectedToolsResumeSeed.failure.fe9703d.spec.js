import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ credentialStatus: vi.fn(), showToast: vi.fn() }))
vi.mock('@/services/api', () => ({ default: { connect: { credentialStatus: h.credentialStatus } } }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.showToast }) }))

import { useConnectedToolsResumeSeed } from '@/composables/useConnectedToolsResumeSeed'

const connected = { data: { connected_harnesses: { 'claude-code': '2026-08-25T00:00:00Z' } } }
const failure = Object.assign(new Error('x'), { response: { status: 500, data: { message: 'status unavailable' } } })

describe('setup resume: a failed connected-tools read', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('is shown, and the next step change retries it', async () => {
    h.credentialStatus.mockRejectedValueOnce(failure).mockResolvedValueOnce(connected)
    const currentStep = ref(2)
    const step2Data = ref({})
    useConnectedToolsResumeSeed({
      currentStep: () => currentStep.value,
      selectedTools: () => ['claude_code'],
      step2Data,
    })
    await flushPromises()

    expect(h.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('status unavailable') }),
    )
    expect(step2Data.value.connectedTools).toBeUndefined()

    currentStep.value = 3
    await nextTick()
    await flushPromises()

    expect(h.credentialStatus).toHaveBeenCalledTimes(2)
    expect(step2Data.value.connectedTools).toEqual(['claude_code'])
  })
})
