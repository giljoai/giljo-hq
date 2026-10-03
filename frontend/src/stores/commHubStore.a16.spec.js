import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCommHubStore } from './commHubStore'
import { parseErrorResponse } from '@/utils/errorMessages'

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      post: vi.fn(),
      passBaton: vi.fn(),
    },
  },
}))

const HINT = 'implementer is a display name held by agent-7 — address agent-7 instead.'

function conflict(errorCode) {
  const err = new Error('Request failed with status code 409')
  err.response = {
    status: 409,
    data: {
      error_code: errorCode,
      message: HINT,
      context: { error: errorCode, registered_id: 'agent-7', next_action_owner: 'orchestrator' },
    },
  }
  return err
}

describe('commHubStore reads a Hub refusal from the 409 status', () => {
  let commHub
  let api

  beforeEach(async () => {
    setActivePinia(createPinia())
    commHub = useCommHubStore()
    api = (await import('@/services/api')).default
  })

  it('postMessage rejects with the server hint on a 409', async () => {
    api.threads.post.mockRejectedValue(conflict('TARGET_IS_A_DISPLAY_NAME'))
    const err = await commHub.postMessage('p1', { content: 'hi' }).catch((e) => e)
    expect(err.response.status).toBe(409)
    expect(parseErrorResponse(err).message).toBe(HINT)
  })

  it('passBaton leaves the local baton alone on a 409', async () => {
    commHub._testSeedThread({ thread_id: 'b1', project_id: null, next_action_owner: 'orchestrator' })
    api.threads.passBaton.mockRejectedValue(conflict('BATON_TARGET_NOT_A_PARTICIPANT'))
    await expect(commHub.passBaton('b1', 'implementer')).rejects.toThrow()
    expect(commHub.threadsById.get('b1').next_action_owner).toBe('orchestrator')
  })

  it('a 200 is a success: the store no longer inspects the body for a refusal', async () => {
    api.threads.post.mockResolvedValue({ data: { success: false, message_id: 'm-1', thread_id: 'p1' } })
    await expect(commHub.postMessage('p1', { content: 'hi' })).resolves.toMatchObject({ message_id: 'm-1' })
  })

  it('passBaton patches the local baton on a real hand-off', async () => {
    commHub._testSeedThread({ thread_id: 'b2', project_id: null, next_action_owner: 'orchestrator' })
    api.threads.passBaton.mockResolvedValue({ data: { thread_id: 'b2', next_action_owner: 'agent-7' } })
    await commHub.passBaton('b2', 'agent-7')
    expect(commHub.threadsById.get('b2').next_action_owner).toBe('agent-7')
  })
})
