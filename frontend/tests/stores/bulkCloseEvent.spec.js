/**
 * Bulk close: one realtime event per batch, one store update, no per-row work.
 *
 * projects:bulk_updated -> projects.handleBulkUpdated (drops the named rows, refreshes once)
 * tasks:bulk_updated    -> tasks.handleBulkUpdated    (updates the named rows, refreshes once)
 * Neither raises a bell row or a lifecycle banner.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { EVENT_MAP, routeWebsocketEvent } from '@/stores/websocketEventRouter'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useNotificationStore } from '@/stores/notifications'

const { mockProjectList, mockProjectGet, mockTaskList, mockProjectBulk, mockTaskBulk, mockDeleted } = vi.hoisted(() => ({
  mockProjectList: vi.fn(),
  mockProjectGet: vi.fn(),
  mockTaskList: vi.fn(),
  mockProjectBulk: vi.fn(),
  mockTaskBulk: vi.fn(),
  mockDeleted: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    projects: { list: mockProjectList, get: mockProjectGet, bulk: mockProjectBulk, fetchDeleted: mockDeleted },
    tasks: { list: mockTaskList, bulk: mockTaskBulk },
  }
  return { api, default: api }
})

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({ currentProductId: null }),
}))

const row = (id, extra = {}) => ({ id, name: id, title: id, hidden: false, ...extra })

describe('bulk close realtime event', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    for (const m of [mockProjectList, mockProjectGet, mockTaskList, mockProjectBulk, mockTaskBulk, mockDeleted]) m.mockReset()
    mockProjectList.mockResolvedValue({ data: [], headers: {} })
    mockTaskList.mockResolvedValue({ data: [] })
    mockDeleted.mockResolvedValue({ data: [], headers: {} })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('20 archived projects arrive as ONE event: rows dropped, one list refresh, no per-project fetch, no bell row', async () => {
    const store = useProjectStore()
    const ids = Array.from({ length: 20 }, (_, i) => `p${i}`)
    store.projects = [...ids.map((id) => row(id)), row('keep')]

    await routeWebsocketEvent(
      { type: 'projects:bulk_updated', data: { action: 'archive', count: 20, ids, truncated: false } },
      { eventMap: EVENT_MAP, storeRegistry: {} },
    )

    expect(store.projects.map((p) => p.id)).toEqual(['keep'])
    await vi.advanceTimersByTimeAsync(1000)
    expect(mockProjectList).toHaveBeenCalledTimes(1)
    expect(mockProjectGet).not.toHaveBeenCalled()
    expect(useNotificationStore().notifications).toHaveLength(0)
  })

  it('an unarchive event keeps the rows it names (they are returning, not leaving)', async () => {
    const store = useProjectStore()
    store.projects = [row('p1')]
    await routeWebsocketEvent(
      { type: 'projects:bulk_updated', data: { action: 'unarchive', count: 1, ids: ['p1'] } },
      { eventMap: EVENT_MAP, storeRegistry: {} },
    )
    expect(store.projects.map((p) => p.id)).toEqual(['p1'])
  })

  it('20 tasks archived elsewhere arrive as ONE event: rows flagged hidden, one list refresh', async () => {
    const store = useTaskStore()
    const ids = Array.from({ length: 20 }, (_, i) => `t${i}`)
    store.tasks = ids.map((id) => row(id))

    await routeWebsocketEvent(
      { type: 'tasks:bulk_updated', data: { action: 'archive', count: 20, ids } },
      { eventMap: EVENT_MAP, storeRegistry: {} },
    )

    expect(store.tasks.every((t) => t.hidden === true)).toBe(true)
    await vi.advanceTimersByTimeAsync(1000)
    expect(mockTaskList).toHaveBeenCalledTimes(1)
  })

  it('a deleted-tasks event removes the rows', async () => {
    const store = useTaskStore()
    store.tasks = [row('t1'), row('t2')]
    await routeWebsocketEvent(
      { type: 'tasks:bulk_updated', data: { action: 'delete', count: 1, ids: ['t1'] } },
      { eventMap: EVENT_MAP, storeRegistry: {} },
    )
    expect(store.tasks.map((t) => t.id)).toEqual(['t2'])
  })

  it('bulkClose sends one request and applies the result once (tasks)', async () => {
    const store = useTaskStore()
    store.tasks = [row('t1'), row('t2')]
    mockTaskBulk.mockResolvedValue({ data: { done: ['t1'], skipped: [{ id: 't2', reason: 'x' }], failed: [] } })

    const result = await store.bulkClose('archive', ['t1', 't2'])

    expect(mockTaskBulk).toHaveBeenCalledTimes(1)
    expect(mockTaskBulk).toHaveBeenCalledWith('archive', ['t1', 't2'])
    expect(result.skipped).toHaveLength(1)
    expect(store.tasks.map((t) => [t.id, t.hidden])).toEqual([
      ['t1', true],
      ['t2', false],
    ])
  })

  it('bulkClose delete (projects) drops rows and reads the trash once', async () => {
    const store = useProjectStore()
    store.projects = [row('p1'), row('p2')]
    mockProjectBulk.mockResolvedValue({ data: { done: ['p1', 'p2'], skipped: [], failed: [] } })

    await store.bulkClose('delete', ['p1', 'p2'])

    expect(mockProjectBulk).toHaveBeenCalledTimes(1)
    expect(store.projects).toEqual([])
    expect(mockDeleted).toHaveBeenCalledTimes(1)
  })
})
