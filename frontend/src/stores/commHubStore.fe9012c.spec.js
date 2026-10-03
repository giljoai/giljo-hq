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
