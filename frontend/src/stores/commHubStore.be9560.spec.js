import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCommHubStore } from './commHubStore'

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      history: vi.fn().mockResolvedValue({ data: { thread: null, messages: [] } }),
      participants: vi.fn().mockResolvedValue({ data: { participants: [] } }),
      post: vi.fn(),
      passBaton: vi.fn(),
    },
  },
}))

describe('commHubStore.postMessage patches the local baton (BE-9560)', () => {
  let commHub
  let api

  beforeEach(async () => {
    setActivePinia(createPinia())
    commHub = useCommHubStore()
    api = (await import('@/services/api')).default
  })

  it('a broadcast reply that clears the baton (baton_cleared) drops next_action_owner locally', async () => {
    commHub._testSeedThread({ thread_id: 't1', project_id: null, next_action_owner: 'user-001' })
    api.threads.post = vi.fn().mockResolvedValue({
      data: {
        message_id: 'm-1',
        thread_id: 't1',
        baton_passed: false,
        baton_cleared: true,
        next_action_owner: null,
      },
    })

    await commHub.postMessage('t1', { content: 'answered' })

    expect(commHub.threadsById.get('t1').next_action_owner).toBeNull()
  })

  it('a directed reply that hands off the baton (baton_passed) moves next_action_owner locally', async () => {
    commHub._testSeedThread({ thread_id: 't2', project_id: null, next_action_owner: 'user-001' })
    api.threads.post = vi.fn().mockResolvedValue({
      data: {
        message_id: 'm-2',
        thread_id: 't2',
        baton_passed: true,
        baton_cleared: false,
        next_action_owner: 'implementer',
      },
    })

    await commHub.postMessage('t2', { to_participant: 'implementer', content: 'over to you' })

    expect(commHub.threadsById.get('t2').next_action_owner).toBe('implementer')
  })

  it('a post that neither passes nor clears the baton leaves it untouched (MCP-parity default)', async () => {
    commHub._testSeedThread({ thread_id: 't3', project_id: null, next_action_owner: 'agent-mid-task' })
    api.threads.post = vi.fn().mockResolvedValue({
      data: {
        message_id: 'm-3',
        thread_id: 't3',
        baton_passed: false,
        baton_cleared: false,
        next_action_owner: 'agent-mid-task',
      },
    })

    await commHub.postMessage('t3', { content: 'FYI, not for agent-mid-task' })

    expect(commHub.threadsById.get('t3').next_action_owner).toBe('agent-mid-task')
  })

  it('a refused post never patches the local baton', async () => {
    commHub._testSeedThread({ thread_id: 't4', project_id: null, next_action_owner: 'user-001' })
    api.threads.post = vi.fn().mockResolvedValue({
      data: {
        success: false,
        error: 'TARGET_IS_A_DISPLAY_NAME',
        thread_id: 't4',
        next_action_owner: 'user-001',
      },
    })

    await expect(commHub.postMessage('t4', { to_participant: 'implementer', content: 'hi' })).rejects.toThrow()
    expect(commHub.threadsById.get('t4').next_action_owner).toBe('user-001')
  })
})
