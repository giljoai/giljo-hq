import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCommHubStore } from './commHubStore'

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      history: vi.fn().mockResolvedValue({ data: { thread: null, messages: [] } }),
      participants: vi.fn().mockResolvedValue({ data: { participants: [] } }),
    },
  },
}))

describe('commHubStore — two-tab split + unread badges (FE-9012c)', () => {
  let commHub

  beforeEach(() => {
    setActivePinia(createPinia())
    commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'p1', project_id: 'projA', updated_at: '2026-07-03T00:00:03Z' })
    commHub._testSeedThread({ thread_id: 'p2', project_id: 'projB', updated_at: '2026-07-03T00:00:02Z' })
    commHub._testSeedThread({ thread_id: 't1', project_id: null, updated_at: '2026-07-03T00:00:01Z' })
  })

  it('projectThreadList holds only project-bound threads, newest-first', () => {
    expect(commHub.projectThreadList.map((t) => t.thread_id)).toEqual(['p1', 'p2'])
  })

  it('townSquareThreadList holds only standalone threads', () => {
    expect(commHub.townSquareThreadList.map((t) => t.thread_id)).toEqual(['t1'])
  })

  it('the two tabs partition the whole thread list (no thread lost or duplicated)', () => {
    const tabbed = [...commHub.projectThreadList, ...commHub.townSquareThreadList].map((t) => t.thread_id).sort()
    expect(tabbed).toEqual(commHub.threadList.map((t) => t.thread_id).sort())
  })

  it('per-tab unread totals sum only that tab’s threads', () => {
    commHub.selectedThreadId = 'unrelated'
    commHub.handleThreadMessage({ thread_id: 'p1', message_id: 'm1', content: 'a' })
    commHub.handleThreadMessage({ thread_id: 'p1', message_id: 'm2', content: 'b' })
    commHub.handleThreadMessage({ thread_id: 'p2', message_id: 'm3', content: 'c' })
    commHub.handleThreadMessage({ thread_id: 't1', message_id: 'm4', content: 'd' })

    expect(commHub.projectUnreadTotal).toBe(3)
    expect(commHub.townSquareUnreadTotal).toBe(1)
  })

  it('normalizeMessage passes D3/D4 recipient junction state through, null when absent', () => {
    commHub.handleThreadMessage({
      thread_id: 'p1',
      message_id: 'withstate',
      content: 'x',
      requires_action: true,
      recipients: ['beta'],
      acked_by: [],
      completed_by: [],
      pending_for: ['beta'],
    })
    commHub.handleThreadMessage({ thread_id: 'p1', message_id: 'nostate', content: 'y' })

    const msgs = commHub.messagesFor('p1')
    const withState = msgs.find((m) => m.message_id === 'withstate')
    const noState = msgs.find((m) => m.message_id === 'nostate')

    expect(withState.recipients).toEqual(['beta'])
    expect(withState.pending_for).toEqual(['beta'])
    expect(noState.recipients).toBeNull()
    expect(noState.pending_for).toBeNull()
  })

  it('loadThread does NOT request recipient state — nothing renders it any more', async () => {
    const api = (await import('@/services/api')).default
    api.threads.history.mockClear()

    await commHub.loadThread('p1')

    expect(api.threads.history).toHaveBeenCalledTimes(1)
    expect(api.threads.history).toHaveBeenCalledWith('p1')
  })
})


const POST_REFUSAL = {
  success: false,
  error: 'TARGET_IS_A_DISPLAY_NAME',
  thread_id: 'p1',
  field: 'to_participant',
  requested: 'implementer',
  registered_id: 'agent-7',
  next_action_owner: 'orchestrator',
  valid_participants: ['agent-7', 'orchestrator'],
  hint: 'implementer is a display name held by agent-7 — address agent-7 instead.',
}

describe('commHubStore refuses to treat a 200 refusal as success (TSK-9300 / TSK-9297)', () => {
  let commHub
  let api

  beforeEach(async () => {
    setActivePinia(createPinia())
    commHub = useCommHubStore()
    api = (await import('@/services/api')).default
  })

  it('postMessage REJECTS on a declined post instead of returning it as sent', async () => {
    api.threads.post = vi.fn().mockResolvedValue({ data: POST_REFUSAL })
    await expect(commHub.postMessage('p1', { content: 'hi' })).rejects.toThrow(
      /display name held by agent-7/,
    )
  })

  it('the thrown error carries the server refusal so a caller can explain it', async () => {
    api.threads.post = vi.fn().mockResolvedValue({ data: POST_REFUSAL })
    const err = await commHub.postMessage('p1', { content: 'hi' }).catch((e) => e)
    expect(err.refusal.error).toBe('TARGET_IS_A_DISPLAY_NAME')
    expect(err.refusal.valid_participants).toContain('agent-7')
  })

  it('postMessage still resolves normally on a real send', async () => {
    api.threads.post = vi.fn().mockResolvedValue({ data: { message_id: 'm-1', thread_id: 'p1' } })
    await expect(commHub.postMessage('p1', { content: 'hi' })).resolves.toMatchObject({
      message_id: 'm-1',
    })
  })

  it('passBaton does NOT move the local baton on a refusal, though it carries a thread_id', async () => {
    commHub._testSeedThread({ thread_id: 'b1', project_id: null, next_action_owner: 'orchestrator' })
    api.threads.passBaton = vi.fn().mockResolvedValue({
      data: { ...POST_REFUSAL, thread_id: 'b1', field: 'pass_baton_to' },
    })
    await expect(commHub.passBaton('b1', 'implementer')).rejects.toThrow()
    expect(commHub.threadsById.get('b1').next_action_owner).toBe('orchestrator')
  })

  it('passBaton still patches the baton on a real hand-off', async () => {
    commHub._testSeedThread({ thread_id: 'b2', project_id: null, next_action_owner: 'orchestrator' })
    api.threads.passBaton = vi.fn().mockResolvedValue({
      data: { thread_id: 'b2', next_action_owner: 'agent-7' },
    })
    await commHub.passBaton('b2', 'agent-7')
    expect(commHub.threadsById.get('b2').next_action_owner).toBe('agent-7')
  })
})
