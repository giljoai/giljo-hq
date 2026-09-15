import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCommHubStore } from '@/stores/commHubStore'

const listMock = vi.fn()
const updateMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: (...args) => listMock(...args),
      update: (...args) => updateMock(...args),
      history: vi.fn(() => Promise.resolve({ data: { thread: null, messages: [] } })),
      participants: vi.fn(() => Promise.resolve({ data: { participants: [] } })),
      create: vi.fn(),
      post: vi.fn(),
      passBaton: vi.fn(),
      delete: vi.fn(),
      search: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
    },
  },
}))

const ENRICHED_THREAD = {
  thread_id: 'thr-1',
  chat_id: 'CHT-0001',
  subject: '(project comms)',
  status: 'open',
  project_id: 'proj-1',
  created_at: '2026-07-25T10:00:00Z',
  title: 'Message Hub redesign',
  project_name: 'Message Hub redesign',
  participants: [{ participant_id: 'agent-a', display_name: 'Alpha', role: 'implementer', harness: 'claude-code' }],
  last_message: { author: 'Alpha', excerpt: 'shipping it', created_at: '2026-07-25T10:05:00Z' },
  unread: true,
}

describe('commHubStore — FE-9289c enriched list + rename', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCommHubStore()
    vi.clearAllMocks()
  })

  it('carries the enriched card fields off the list payload', async () => {
    listMock.mockResolvedValueOnce({ data: { threads: [ENRICHED_THREAD] } })
    await store.loadThreads()

    const t = store.threadsById.get('thr-1')
    expect(t.title).toBe('Message Hub redesign')
    expect(t.project_name).toBe('Message Hub redesign')
    expect(t.participants[0].harness).toBe('claude-code')
    expect(t.last_message.excerpt).toBe('shipping it')
    expect(t.unread).toBe(true)
  })

  it('a partial thread_update does NOT wipe the enriched fields', async () => {
    listMock.mockResolvedValueOnce({ data: { threads: [ENRICHED_THREAD] } })
    await store.loadThreads()

    store.handleThreadUpdate({ thread_id: 'thr-1', status: 'resolved', next_action_owner: 'user-1' })

    const t = store.threadsById.get('thr-1')
    expect(t.status).toBe('resolved')
    expect(t.next_action_owner).toBe('user-1')
    expect(t.participants[0].display_name).toBe('Alpha')
    expect(t.last_message.excerpt).toBe('shipping it')
    expect(t.unread).toBe(true)
  })

  it('renameThread PATCHes and patches the local subject + title on success', async () => {
    listMock.mockResolvedValueOnce({ data: { threads: [{ ...ENRICHED_THREAD, project_id: null }] } })
    await store.loadThreads()

    updateMock.mockResolvedValueOnce({ data: { thread_id: 'thr-1', subject: 'Deploy coordination', title: 'Deploy coordination' } })
    await store.renameThread('thr-1', 'Deploy coordination')

    expect(updateMock).toHaveBeenCalledWith('thr-1', { subject: 'Deploy coordination' })
    const t = store.threadsById.get('thr-1')
    expect(t.subject).toBe('Deploy coordination')
    expect(t.title).toBe('Deploy coordination')
  })

  it('renameThread throws on rejection so the caller can surface the reason', async () => {
    const rejection = new Error('project thread cannot be renamed')
    updateMock.mockRejectedValueOnce(rejection)

    await expect(store.renameThread('thr-1', 'nope')).rejects.toThrow('project thread cannot be renamed')
  })
})
