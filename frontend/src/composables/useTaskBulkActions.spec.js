import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, computed, nextTick } from 'vue'
import { useTaskBulkActions, PENDING_HANDOVER_REASON } from './useTaskBulkActions'

const mockBulkClose = vi.fn()
const mockShowToast = vi.fn()

vi.mock('@/stores/tasks', () => ({
  useTaskStore: () => ({ bulkClose: mockBulkClose }),
}))
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

const plain = (id, extra = {}) => ({ id, title: id, status: 'pending', hidden: false, ...extra })
const pendingHandover = plain('h1', { taxonomy_alias: 'HND-0001', task_type: { abbreviation: 'HND' } })

function setup(tasks) {
  const visibleTasks = ref(tasks)
  const search = ref('')
  const api = useTaskBulkActions({ visibleTasks, filterKeys: computed(() => [search.value]) })
  return { api, search }
}

describe('useTaskBulkActions', () => {
  beforeEach(() => {
    mockBulkClose.mockReset().mockImplementation(async (_action, ids) => ({ done: ids, skipped: [], failed: [] }))
    mockShowToast.mockReset()
  })

  it('archives the ticked rows in one request, skips a pending handover and names it', async () => {
    const tasks = [plain('t1'), plain('t2'), pendingHandover]
    const { api } = setup(tasks)
    api.onSelectedIds(['t1', 't2', 'h1'])

    const result = await api.archiveSelected()

    expect(mockBulkClose.mock.calls).toEqual([['archive', ['t1', 't2']]])
    expect(result.skipped).toEqual([{ row: pendingHandover, reason: PENDING_HANDOVER_REASON }])
    expect(mockShowToast).toHaveBeenCalledWith({
      message: `2 archived, 1 skipped: ${PENDING_HANDOVER_REASON}`,
      type: 'warning',
    })
    expect(api.bulk.selectedIds.value).toEqual(['h1'])
  })

  it('deleting 20 selected tasks is ONE request and ONE toast', async () => {
    const tasks = Array.from({ length: 20 }, (_, i) => plain(`t${i}`))
    const { api } = setup(tasks)
    api.onSelectedIds(tasks.map((t) => t.id))

    await api.deleteSelected()

    expect(mockBulkClose).toHaveBeenCalledTimes(1)
    expect(mockBulkClose.mock.calls[0][0]).toBe('delete')
    expect(mockBulkClose.mock.calls[0][1]).toHaveLength(20)
    expect(mockShowToast).toHaveBeenCalledTimes(1)
    expect(mockShowToast).toHaveBeenCalledWith({ message: '20 deleted', type: 'success' })
  })

  it('an archived handover (not pending) is archivable like any task', async () => {
    const readHandover = { ...pendingHandover, status: 'completed' }
    const { api } = setup([readHandover])
    api.onSelectedIds(['h1'])
    const result = await api.archiveSelected()
    expect(result.done).toEqual([readHandover])
  })

  it('reports a server refusal with its reason instead of failing the batch', async () => {
    mockBulkClose.mockResolvedValueOnce({
      done: ['t2'],
      skipped: [],
      failed: [{ id: 't1', reason: 'Task is locked' }],
    })
    const { api } = setup([plain('t1'), plain('t2')])
    api.onSelectedIds(['t1', 't2'])

    const result = await api.deleteSelected()

    expect(mockBulkClose).toHaveBeenCalledTimes(1)
    expect(result.done.map((t) => t.id)).toEqual(['t2'])
    expect(mockShowToast).toHaveBeenCalledWith({ message: '1 deleted, 1 failed: Task is locked', type: 'warning' })
    expect(api.bulk.selectedIds.value).toEqual(['t1'])
  })

  it('offers Unarchive only for archived rows and unarchives only those', async () => {
    const { api } = setup([plain('t1'), plain('t2', { hidden: true })])
    api.onSelectedIds(['t1', 't2'])
    expect(api.canArchive.value).toBe(true)
    expect(api.canUnarchive.value).toBe(true)

    await api.unarchiveSelected()
    expect(mockBulkClose.mock.calls).toEqual([['unarchive', ['t2']]])
  })

  it('select all matching takes every row in the filtered view', () => {
    const { api } = setup([plain('t1'), plain('t2'), plain('t3')])
    api.selectAllMatching()
    expect(api.bulk.count.value).toBe(3)
    expect(api.bulk.allMatching.value).toBe(true)
  })

  it('a filter change clears the selection (never act on rows out of view)', async () => {
    const { api, search } = setup([plain('t1')])
    api.onSelectedIds(['t1'])
    search.value = 'something'
    await nextTick()
    expect(api.bulk.count.value).toBe(0)
  })
})
