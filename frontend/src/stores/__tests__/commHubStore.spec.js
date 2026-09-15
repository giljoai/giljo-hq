import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCommHubStore } from '@/stores/commHubStore'

const listMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: (...args) => listMock(...args),
      history: vi.fn(() => Promise.resolve({ data: { thread: null, messages: [] } })),
      participants: vi.fn(() => Promise.resolve({ data: { participants: [] } })),
      create: vi.fn(),
      post: vi.fn(),
      passBaton: vi.fn(),
      search: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
    },
  },
}))

const THREAD_1 = {
  thread_id: 'thr-001',
  chat_id: 'CHT-0001',
  subject: 'First thread',
  status: 'open',
  next_action_owner: null,
  severity: 'normal',
  product_id: null,
  project_id: null,
  created_at: '2026-06-17T10:00:00Z',
  last_activity_at: '2026-06-17T10:00:00Z',
}

const MSG_1 = {
  message_id: 'msg-001',
  thread_id: 'thr-001',
  from_agent_id: 'orchestrator',
  from_display_name: 'orchestrator',
  content: 'Hello world',
  message_type: 'broadcast',
  priority: 'normal',
  status: null,
  requires_action: false,
  created_at: '2026-06-17T10:01:00Z',
}

describe('commHubStore', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCommHubStore()
    listMock.mockReset()
    listMock.mockResolvedValue({ data: { threads: [], count: 0 } })
  })

  it('normalizeMessage: produces expected shape from handleThreadMessage', () => {
    store.handleThreadMessage(MSG_1)
    const messages = store.messagesFor('thr-001')
    expect(messages).toHaveLength(1)
    const m = messages[0]
    expect(m.message_id).toBe('msg-001')
    expect(m.thread_id).toBe('thr-001')
    expect(m.from_display_name).toBe('orchestrator')
    expect(m.content).toBe('Hello world')
    expect(m.message_type).toBe('broadcast')
  })

  it('handleThreadMessage: appends new message to the store', () => {
    store.handleThreadMessage(MSG_1)
    expect(store.messagesFor('thr-001')).toHaveLength(1)
  })

  it('handleThreadMessage: dedupes by message_id (second call with same id is a no-op)', () => {
    store.handleThreadMessage(MSG_1)
    store.handleThreadMessage(MSG_1)
    expect(store.messagesFor('thr-001')).toHaveLength(1)
  })

  it('handleThreadMessage: immutable — original list is not mutated', () => {
    store.handleThreadMessage(MSG_1)
    const listBefore = store.messagesFor('thr-001')

    const MSG_2 = { ...MSG_1, message_id: 'msg-002', content: 'Second message' }
    store.handleThreadMessage(MSG_2)

    expect(listBefore).toHaveLength(1)
    expect(store.messagesFor('thr-001')).toHaveLength(2)
  })

  it('handleThreadMessage: updates existing message (same message_id, new content)', () => {
    store.handleThreadMessage(MSG_1)
    const updated = { ...MSG_1, content: 'Updated content', requires_action: true }
    store.handleThreadMessage(updated)
    const messages = store.messagesFor('thr-001')
    expect(messages).toHaveLength(1)
    expect(messages[0].content).toBe('Updated content')
    expect(messages[0].requires_action).toBe(true)
  })

  it('handleThreadUpdate: patches status on existing thread', () => {
    store.handleThreadMessage(MSG_1)
    listMock.mockResolvedValueOnce({ data: { threads: [THREAD_1], count: 1 } })

    return store.loadThreads().then(() => {
      expect(store.threadsById.has('thr-001')).toBe(true)

      store.handleThreadUpdate({
        thread_id: 'thr-001',
        status: 'closed',
        next_action_owner: null,
        update_type: 'status',
      })

      const thread = store.threadsById.get('thr-001')
      expect(thread.status).toBe('closed')
    })
  })

  it('handleThreadUpdate: patches next_action_owner', () => {
    listMock.mockResolvedValueOnce({ data: { threads: [THREAD_1], count: 1 } })
    return store.loadThreads().then(() => {
      store.handleThreadUpdate({
        thread_id: 'thr-001',
        next_action_owner: 'implementer',
        update_type: 'baton',
      })
      expect(store.threadsById.get('thr-001').next_action_owner).toBe('implementer')
    })
  })

  it('handleThreadUpdate: update_type "created" with unknown thread triggers loadThreads', async () => {
    listMock.mockResolvedValue({ data: { threads: [], count: 0 } })

    store.handleThreadUpdate({
      thread_id: 'thr-unknown',
      chat_id: 'CHT-9999',
      status: 'open',
      update_type: 'created',
    })

    await new Promise((r) => setTimeout(r, 0))
    expect(listMock).toHaveBeenCalled()
  })

  it('handleThreadUpdate: "created" for an ALREADY known thread does NOT trigger loadThreads', async () => {
    listMock.mockResolvedValueOnce({ data: { threads: [THREAD_1], count: 1 } })
    await store.loadThreads()
    listMock.mockClear()

    store.handleThreadUpdate({
      thread_id: 'thr-001',
      status: 'open',
      update_type: 'created',
    })

    await new Promise((r) => setTimeout(r, 0))
    expect(listMock).not.toHaveBeenCalled()
  })

  it('$reset clears all state', () => {
    store.handleThreadMessage(MSG_1)
    store.selectedThreadId = 'thr-001'
    store.$reset()
    expect(store.messagesFor('thr-001')).toHaveLength(0)
    expect(store.selectedThreadId).toBeNull()
    expect(store.threadList).toHaveLength(0)
  })

  it('threadList is sorted newest last_activity_at first', async () => {
    const older = { ...THREAD_1, thread_id: 'thr-older', last_activity_at: '2026-06-17T08:00:00Z' }
    const newer = { ...THREAD_1, thread_id: 'thr-newer', last_activity_at: '2026-06-17T12:00:00Z' }
    listMock.mockResolvedValueOnce({ data: { threads: [older, newer], count: 2 } })
    await store.loadThreads()
    const list = store.threadList
    expect(list[0].thread_id).toBe('thr-newer')
    expect(list[1].thread_id).toBe('thr-older')
  })
})
