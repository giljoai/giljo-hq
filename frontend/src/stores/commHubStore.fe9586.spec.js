/**
 * commHubStore.fe9586.spec.js — FE-9586
 *
 * Opening a thread must tell the SERVER it was read.
 *
 * The defect: markThreadRead() zeroed an in-memory counter and persisted nothing,
 * and the REST history read passes no mark_read, so comm_participants.last_read_at
 * — the cursor the card's `unread` flag keys on — was advanced only by agents over
 * MCP. The operator had no watermark and every card read unread forever.
 *
 * The rules pinned here are the decided conditions on write-on-open, and each is a
 * test rather than a comment because each is a way to get this subtly wrong:
 *  - it fires on a genuine open;
 *  - it is fire-and-forget — a rejected write must not throw out of selectThread,
 *    because a failed watermark must never break the thread view;
 *  - closing the pane (id null) writes nothing, so "no thread" is not a thread.
 */
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
    // and the selection still happened — the view must not depend on the write
    expect(useCommHubStore().selectedThreadId).toBe('thr-1')
  })

  it('still clears the local counter, so the UI does not wait for the round trip', () => {
    const store = useCommHubStore()
    store.handleThreadMessage({ thread_id: 'thr-2', message_id: 'm1', content: 'hi' })

    store.selectThread('thr-2')

    expect(store.unreadFor('thr-2')).toBe(0)
  })
})
