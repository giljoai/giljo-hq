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
      // FE-9586: selectThread persists the operator's read watermark.
      markRead: vi.fn().mockResolvedValue({ data: {} }),
      participants: vi.fn().mockResolvedValue({ data: { participants: [] } }),
      create: vi.fn(),
      update: vi.fn(),
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

// FE-9528: the Hub ignores the viewed product tab. The backend filter
// (comm_threads.py list_threads) and the store field (filters.product_id)
// both existed; nothing read productStore.currentProductId to populate it.
// Mirrors the BE-9525a precedent (projects.spec.js — "per-product scoping").
describe('commHubStore — Hub follows viewed product (FE-9528)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('loadThreads scopes the request to the viewed product via currentProductId', async () => {
    const api = (await import('@/services/api')).default
    const { useProductStore } = await import('@/stores/products')
    const commHub = useCommHubStore()
    const productStore = useProductStore()
    productStore.currentProductId = 'product-b'

    await commHub.loadThreads()

    expect(api.threads.list).toHaveBeenCalledWith(
      expect.objectContaining({ product_id: 'product-b' }),
    )
  })

  it('loadThreads sends no product_id when no product tab is viewed', async () => {
    const api = (await import('@/services/api')).default
    const commHub = useCommHubStore()

    await commHub.loadThreads()

    const params = api.threads.list.mock.calls.at(-1)[0]
    expect(params).not.toHaveProperty('product_id')
  })

  it('an explicit filter product_id is not clobbered by the viewed tab', async () => {
    const api = (await import('@/services/api')).default
    const { useProductStore } = await import('@/stores/products')
    const commHub = useCommHubStore()
    const productStore = useProductStore()
    productStore.currentProductId = 'product-b'

    await commHub.loadThreads({ product_id: 'product-a' })

    expect(api.threads.list).toHaveBeenCalledWith(
      expect.objectContaining({ product_id: 'product-a' }),
    )
  })

  // Product-less threads are LEGAL (BE-9523b) and must not become invisible
  // (the FE-9502d defect, repeated one surface over, is exactly this). The
  // scoped list (loadThreads/threadList) excludes them once a product tab
  // filters strictly — searchThreads is their documented destination: the
  // backend /threads/search endpoint (comm_threads.search_threads — the REST
  // handler, not the retired MCP tool of that name)
  // takes no product_id at all, so it is unscoped by construction and finds
  // a standalone thread no matter which product tab is open.
  // The cache (threadsById) is an upsert Map fed by WS across every product
  // (FE-9502d: background-product events keep arriving while another tab is
  // viewed), never wholesale-replaced like projects.js/tasks.js. Scoping only
  // the FETCH leaves an already-cached other-product thread visible in the
  // list after switching tabs — the getter must also filter by the viewed
  // product, or "switching tabs shows only that product's threads" is false.
  it('threadList excludes a cached thread from a different product than the viewed tab', async () => {
    const { useProductStore } = await import('@/stores/products')
    const commHub = useCommHubStore()
    const productStore = useProductStore()
    commHub._testSeedThread({ thread_id: 'thread-a', product_id: 'product-a', status: 'open' })
    commHub._testSeedThread({ thread_id: 'thread-b', product_id: 'product-b', status: 'open' })

    productStore.currentProductId = 'product-b'

    expect(commHub.threadList.map((t) => t.thread_id)).toEqual(['thread-b'])
  })

  it('threadList shows every product\'s threads when no product tab is viewed', async () => {
    const commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'thread-a', product_id: 'product-a', status: 'open' })
    commHub._testSeedThread({ thread_id: 'thread-b', product_id: 'product-b', status: 'open' })

    expect(commHub.threadList.map((t) => t.thread_id).sort()).toEqual(['thread-a', 'thread-b'])
  })

  it('searchThreads stays unscoped by the viewed product (product-less threads stay reachable)', async () => {
    const api = (await import('@/services/api')).default
    const { useProductStore } = await import('@/stores/products')
    const commHub = useCommHubStore()
    const productStore = useProductStore()
    productStore.currentProductId = 'product-b'
    api.threads.search.mockResolvedValueOnce({
      data: { threads: [{ thread_id: 'standalone-1', product_id: null, subject: 'orphan' }] },
    })

    const results = await commHub.searchThreads('orphan')

    expect(api.threads.search).toHaveBeenCalledWith({ query: 'orphan' })
    expect(results.map((t) => t.thread_id)).toContain('standalone-1')
  })
})

// FE-9530: FE-9528's viewed-product scoping becomes the DEFAULT filter, not a
// hard scope. One Hub space, every thread reachable via productScope='all';
// 'unassigned' is the explicit way to find what ruling 2's "no migration"
// left untagged. Every test above this block must keep passing UNCHANGED —
// productScope defaults to 'viewed', which is byte-identical to FE-9528.
describe('commHubStore — one Hub space, widenable product filter (FE-9530)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('defaults to productScope "viewed" — the FE-9528 behaviour, unchanged', () => {
    const commHub = useCommHubStore()
    expect(commHub.productScope).toBe('viewed')
  })

  it('setProductScope("all") widens threadList to every product, INCLUDING product-less', async () => {
    const { useProductStore } = await import('@/stores/products')
    const commHub = useCommHubStore()
    const productStore = useProductStore()
    productStore.currentProductId = 'product-b'
    commHub._testSeedThread({ thread_id: 'thread-a', product_id: 'product-a', status: 'open' })
    commHub._testSeedThread({ thread_id: 'thread-b', product_id: 'product-b', status: 'open' })
    commHub._testSeedThread({ thread_id: 'thread-none', product_id: null, status: 'open' })

    commHub.setProductScope('all')

    expect(commHub.threadList.map((t) => t.thread_id).sort()).toEqual(['thread-a', 'thread-b', 'thread-none'])
  })

  it('setProductScope("unassigned") shows ONLY product-less threads, even with a product viewed', async () => {
    const { useProductStore } = await import('@/stores/products')
    const commHub = useCommHubStore()
    const productStore = useProductStore()
    productStore.currentProductId = 'product-b'
    commHub._testSeedThread({ thread_id: 'thread-b', product_id: 'product-b', status: 'open' })
    commHub._testSeedThread({ thread_id: 'thread-none', product_id: null, status: 'open' })

    commHub.setProductScope('unassigned')

    expect(commHub.threadList.map((t) => t.thread_id)).toEqual(['thread-none'])
  })

  it('an unknown scope is ignored — productScope stays at its current value', () => {
    const commHub = useCommHubStore()
    commHub.setProductScope('bogus')
    expect(commHub.productScope).toBe('viewed')
  })

  it('loadThreads does NOT inject product_id when scope is "all"', async () => {
    const api = (await import('@/services/api')).default
    const { useProductStore } = await import('@/stores/products')
    const commHub = useCommHubStore()
    const productStore = useProductStore()
    productStore.currentProductId = 'product-b'
    commHub.setProductScope('all')

    await commHub.loadThreads()

    const params = api.threads.list.mock.calls.at(-1)[0]
    expect(params).not.toHaveProperty('product_id')
  })

  it('retagThread sets product_id via PATCH and patches the cached thread', async () => {
    const api = (await import('@/services/api')).default
    const commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'thread-a', product_id: null, project_ids: [], status: 'open' })
    api.threads.update.mockResolvedValueOnce({
      data: { thread_id: 'thread-a', product_id: 'product-a', project_ids: [] },
    })

    await commHub.retagThread('thread-a', { productId: 'product-a' })

    expect(api.threads.update).toHaveBeenCalledWith('thread-a', { product_id: 'product-a' })
    expect(commHub.threadsById.get('thread-a').product_id).toBe('product-a')
  })

  it('retagThread("") clears the product via clear_product', async () => {
    const api = (await import('@/services/api')).default
    const commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'thread-a', product_id: 'product-a', project_ids: [], status: 'open' })
    api.threads.update.mockResolvedValueOnce({
      data: { thread_id: 'thread-a', product_id: null, project_ids: [] },
    })

    await commHub.retagThread('thread-a', { productId: '' })

    expect(api.threads.update).toHaveBeenCalledWith('thread-a', { clear_product: true })
    expect(commHub.threadsById.get('thread-a').product_id).toBeNull()
  })

  it('retagThread replaces project_ids and patches the cache', async () => {
    const api = (await import('@/services/api')).default
    const commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'thread-a', product_id: 'product-a', project_ids: [], status: 'open' })
    api.threads.update.mockResolvedValueOnce({
      data: { thread_id: 'thread-a', product_id: 'product-a', project_ids: ['project-1', 'project-2'] },
    })

    await commHub.retagThread('thread-a', { projectIds: ['project-1', 'project-2'] })

    expect(api.threads.update).toHaveBeenCalledWith('thread-a', { project_ids: ['project-1', 'project-2'] })
    expect(commHub.threadsById.get('thread-a').project_ids).toEqual(['project-1', 'project-2'])
  })

  it('retagThread with nothing to change makes no API call', async () => {
    const api = (await import('@/services/api')).default
    const commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'thread-a', product_id: null, project_ids: [], status: 'open' })

    await commHub.retagThread('thread-a', {})

    expect(api.threads.update).not.toHaveBeenCalled()
  })

  it('normalizeThread carries project_ids, defaulting to [] rather than null', () => {
    const commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'thread-a', product_id: null, status: 'open' })

    expect(commHub.threadsById.get('thread-a').project_ids).toEqual([])
  })
})
