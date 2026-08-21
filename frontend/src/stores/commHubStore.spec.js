/**
 * commHubStore.spec.js — FE-6054f
 * Tests for unread + baton additions to commHubStore.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCommHubStore } from './commHubStore'
import { useUserStore } from '@/stores/user'

// Mock the API so loadThread/loadThreads don't need real axios
vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      history: vi.fn().mockResolvedValue({ data: { thread: null, messages: [] } }),
      participants: vi.fn().mockResolvedValue({ data: { participants: [] } }),
      create: vi.fn(),
      post: vi.fn(),
      passBaton: vi.fn(),
      delete: vi.fn().mockResolvedValue({ data: { deleted: true } }),
      search: vi.fn().mockResolvedValue({ data: { threads: [] } }),
    },
  },
}))

describe('commHubStore — unread + baton (FE-6054f)', () => {
  let commHub
  let userStore

  beforeEach(() => {
    setActivePinia(createPinia())
    commHub = useCommHubStore()
    userStore = useUserStore()
    // Seed a current user
    userStore.currentUser = {
      id: 'user-001',
      display_name: 'Sam Rivera',
      tenant_key: 'tenant-abc',
    }
    // Seed a thread so handleThreadMessage has context
    commHub._testSeedThread({ thread_id: 'thread-1', status: 'open', next_action_owner: null })
    commHub._testSeedThread({ thread_id: 'thread-2', status: 'open', next_action_owner: null })
  })

  // ── unread ──

  it('increments unread for a non-selected thread on handleThreadMessage', () => {
    commHub.selectedThreadId = 'thread-2' // thread-1 is NOT selected
    commHub.handleThreadMessage({
      thread_id: 'thread-1',
      message_id: 'msg-1',
      from_agent_id: 'agent-x',
      content: 'hello',
    })
    expect(commHub.unreadFor('thread-1')).toBe(1)
    expect(commHub.totalUnread).toBe(1)
  })

  it('does NOT increment unread for the currently selected thread', () => {
    commHub.selectedThreadId = 'thread-1'
    commHub.handleThreadMessage({
      thread_id: 'thread-1',
      message_id: 'msg-2',
      from_agent_id: 'agent-x',
      content: 'hello',
    })
    expect(commHub.unreadFor('thread-1')).toBe(0)
    expect(commHub.totalUnread).toBe(0)
  })

  it('accumulates multiple unread counts', () => {
    commHub.selectedThreadId = 'thread-2'
    for (let i = 0; i < 3; i++) {
      commHub.handleThreadMessage({
        thread_id: 'thread-1',
        message_id: `msg-${i}`,
        from_agent_id: 'agent-x',
        content: 'hi',
      })
    }
    expect(commHub.unreadFor('thread-1')).toBe(3)
    expect(commHub.totalUnread).toBe(3)
  })

  it('markThreadRead sets unread to 0', () => {
    commHub.selectedThreadId = 'thread-2'
    commHub.handleThreadMessage({
      thread_id: 'thread-1',
      message_id: 'msg-3',
      from_agent_id: 'agent-x',
      content: 'hi',
    })
    expect(commHub.unreadFor('thread-1')).toBe(1)
    commHub.markThreadRead('thread-1')
    expect(commHub.unreadFor('thread-1')).toBe(0)
    expect(commHub.totalUnread).toBe(0)
  })

  it('selectThread clears unread for the selected thread', () => {
    commHub.selectedThreadId = 'thread-2'
    commHub.handleThreadMessage({
      thread_id: 'thread-1',
      message_id: 'msg-4',
      from_agent_id: 'agent-x',
      content: 'hi',
    })
    expect(commHub.unreadFor('thread-1')).toBe(1)
    commHub.selectThread('thread-1')
    expect(commHub.unreadFor('thread-1')).toBe(0)
  })

  // ── baton ──

  it('batonThreadIds includes threads where next_action_owner === currentUser.id', () => {
    commHub.handleThreadUpdate({
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })
    expect(commHub.batonThreadIds).toContain('thread-1')
    expect(commHub.yourTurnCount).toBe(1)
  })

  it('batonThreadIds excludes threads owned by someone else', () => {
    commHub.handleThreadUpdate({
      thread_id: 'thread-1',
      next_action_owner: 'agent-xyz',
    })
    expect(commHub.batonThreadIds).not.toContain('thread-1')
    expect(commHub.yourTurnCount).toBe(0)
  })

  it('hasUserAttention is true when totalUnread > 0', () => {
    commHub.selectedThreadId = 'thread-2'
    commHub.handleThreadMessage({
      thread_id: 'thread-1',
      message_id: 'msg-5',
      from_agent_id: 'agent-x',
      content: 'hello',
    })
    expect(commHub.hasUserAttention).toBe(true)
  })

  it('hasUserAttention is true when yourTurnCount > 0', () => {
    commHub.handleThreadUpdate({ thread_id: 'thread-1', next_action_owner: 'user-001' })
    expect(commHub.hasUserAttention).toBe(true)
  })

  it('hasUserAttention is false when nothing pending', () => {
    expect(commHub.hasUserAttention).toBe(false)
  })

  // ── soft delete ──

  it('deleteThread calls the API and removes the thread from local state', async () => {
    const api = (await import('@/services/api')).default
    commHub.selectThread('thread-1')
    expect(commHub.threadsById.has('thread-1')).toBe(true)

    await commHub.deleteThread('thread-1')

    expect(api.threads.delete).toHaveBeenCalledWith('thread-1')
    expect(commHub.threadsById.has('thread-1')).toBe(false)
    // Selection cleared because the deleted thread was open
    expect(commHub.selectedThreadId).toBe(null)
    // thread-2 untouched
    expect(commHub.threadsById.has('thread-2')).toBe(true)
  })

  it('deleteThread keeps the selection when a different thread is open', async () => {
    commHub.selectThread('thread-2')
    await commHub.deleteThread('thread-1')
    expect(commHub.threadsById.has('thread-1')).toBe(false)
    expect(commHub.selectedThreadId).toBe('thread-2')
  })

  it('handleThreadUpdate(update_type=deleted) drops the thread locally', () => {
    commHub.selectThread('thread-1')
    commHub.handleThreadUpdate({ thread_id: 'thread-1', update_type: 'deleted' })
    expect(commHub.threadsById.has('thread-1')).toBe(false)
    expect(commHub.selectedThreadId).toBe(null)
  })

  // ── $reset ──

  it('$reset clears unreadByThreadId', () => {
    commHub.selectedThreadId = 'thread-2'
    commHub.handleThreadMessage({
      thread_id: 'thread-1',
      message_id: 'msg-6',
      from_agent_id: 'agent-x',
      content: 'hi',
    })
    expect(commHub.totalUnread).toBe(1)
    commHub.$reset()
    expect(commHub.totalUnread).toBe(0)
    expect(commHub.unreadByThreadId.size).toBe(0)
  })
})
