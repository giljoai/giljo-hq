import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, computed, nextTick } from 'vue'
import { useTaskBulkActions, PENDING_HANDOVER_REASON } from './useTaskBulkActions'

const mockUpdateTask = vi.fn()
const mockDeleteTask = vi.fn()
const mockShowToast = vi.fn()

vi.mock('@/stores/tasks', () => ({
  useTaskStore: () => ({ updateTask: mockUpdateTask, deleteTask: mockDeleteTask }),
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
    mockUpdateTask.mockReset().mockResolvedValue({})
    mockDeleteTask.mockReset().mockResolvedValue(undefined)
    mockShowToast.mockReset()
  })

  it('archives ticked rows one by one, skips a pending handover and names it', async () => {
    const tasks = [plain('t1'), plain('t2'), pendingHandover]
    const { api } = setup(tasks)
    api.onSelectedIds(['t1', 't2', 'h1'])

    const result = await api.archiveSelected()

    expect(mockUpdateTask.mock.calls).toEqual([
      ['t1', { hidden: true }],
      ['t2', { hidden: true }],
    ])
    expect(result.skipped).toEqual([{ row: pendingHandover, reason: PENDING_HANDOVER_REASON }])
    expect(mockShowToast).toHaveBeenCalledWith({
      message: `2 archived, 1 skipped: ${PENDING_HANDOVER_REASON}`,
      type: 'warning',
    })
    expect(api.bulk.selectedIds.value).toEqual(['h1'])
  })

  it('an archived handover (not pending) is archivable like any task', async () => {
    const readHandover = { ...pendingHandover, status: 'completed' }
    const { api } = setup([readHandover])
    api.onSelectedIds(['h1'])
    const result = await api.archiveSelected()
    expect(result.done).toEqual([readHandover])
  })

  it('reports a server refusal with its reason instead of failing the batch', async () => {
    mockDeleteTask.mockRejectedValueOnce({ response: { data: { detail: 'Task is locked' } } })
    const { api } = setup([plain('t1'), plain('t2')])
    api.onSelectedIds(['t1', 't2'])

    const result = await api.deleteSelected()

    expect(mockDeleteTask).toHaveBeenCalledTimes(2)
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
    expect(mockUpdateTask.mock.calls).toEqual([['t2', { hidden: false }]])
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
