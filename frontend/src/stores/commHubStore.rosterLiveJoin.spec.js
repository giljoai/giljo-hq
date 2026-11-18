import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCommHubStore } from '@/stores/commHubStore'

const participantsMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    threads: {
      markRead: vi.fn(() => Promise.resolve({ data: {} })),
      list: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      history: vi.fn(() => Promise.resolve({ data: { thread: null, messages: [] } })),
      participants: (...args) => participantsMock(...args),
    },
  },
}))

const agent = (id) => ({ participant_id: id, participant_type: 'agent', display_name: id })

function post(id, from) {
  return { thread_id: 'thr-1', message_id: id, from_agent_id: from, content: 'hi', created_at: '2026-11-07T16:56:30Z' }
}

describe('thread roster picks up an agent that joins after the thread was opened', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    participantsMock.mockReset()
  })

  it('a post from an author not on the loaded roster re-reads the roster', async () => {
    const store = useCommHubStore()
    participantsMock.mockResolvedValueOnce({ data: { participants: [agent('a1')] } })
    await store.loadParticipants('thr-1')

    participantsMock.mockResolvedValueOnce({ data: { participants: [agent('a1'), agent('cto')] } })
    await store.handleThreadMessage(post('m1', 'cto'))

    expect(participantsMock).toHaveBeenCalledTimes(2)
    expect(store.participantsFor('thr-1').map((p) => p.participant_id)).toEqual(['a1', 'cto'])
  })

  it('a post from an author already on the roster costs no read', async () => {
    const store = useCommHubStore()
    participantsMock.mockResolvedValue({ data: { participants: [agent('a1')] } })
    await store.loadParticipants('thr-1')

    await store.handleThreadMessage(post('m1', 'a1'))

    expect(participantsMock).toHaveBeenCalledTimes(1)
  })

  it('a thread whose roster was never loaded is not fetched for', async () => {
    const store = useCommHubStore()

    await store.handleThreadMessage(post('m1', 'cto'))

    expect(participantsMock).not.toHaveBeenCalled()
  })
})
