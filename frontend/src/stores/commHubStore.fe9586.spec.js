import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCommHubStore } from '@/stores/commHubStore'

const markReadMock = vi.fn(() => Promise.resolve({ data: {} }))
vi.mock('@/services/api', () => ({
  default: {
    threads: {
      markRead: (...args) => markReadMock(...args),
      list: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      history: vi.fn(() => Promise.resolve({ data: { thread: null, messages: [] } })),
      participants: vi.fn(() => Promise.resolve({ data: { participants: [] } })),
    },
  },
}))

describe('commHubStore write-on-open watermark (FE-9586)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    markReadMock.mockClear()
    markReadMock.mockImplementation(() => Promise.resolve({ data: {} }))
  })

  it('THE FIX: selecting a thread persists the read watermark server-side', () => {
    useCommHubStore().selectThread('thr-1')

    expect(markReadMock).toHaveBeenCalledWith('thr-1')
  })

  it('closing the pane writes nothing — a null selection is not a thread', () => {
    useCommHubStore().selectThread(null)

    expect(markReadMock).not.toHaveBeenCalled()
  })

  it('is fire-and-forget: a rejected write does not throw out of selectThread', () => {
    markReadMock.mockImplementation(() => Promise.reject(new Error('offline')))

    expect(() => useCommHubStore().selectThread('thr-1')).not.toThrow()
    expect(useCommHubStore().selectedThreadId).toBe('thr-1')
  })

  it('still clears the local counter, so the UI does not wait for the round trip', () => {
    const store = useCommHubStore()
    store.handleThreadMessage({ thread_id: 'thr-2', message_id: 'm1', content: 'hi' })

    store.selectThread('thr-2')

    expect(store.unreadFor('thr-2')).toBe(0)
  })
})
