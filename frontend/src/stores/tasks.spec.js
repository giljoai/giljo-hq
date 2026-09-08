/**
 * tasks.spec.js — FE-9501c (D9)
 *
 * The Tasks filter clobber: a WS-driven refresh must replay the LAST
 * fetchTasks() params (product_id / filter_type), not refetch paramless and
 * reset the user's filter out from under them. Mirrors projects.js's
 * _lastListOpts/refreshList pattern.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockTasksList = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    tasks: {
      list: (...a) => mockTasksList(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

import { useTaskStore } from './tasks'
import { useProductStore } from './products'

describe('tasks store — FE-9501c (D9) refreshList replays the last filter', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockTasksList.mockResolvedValue({ data: [] })
  })

  it('refreshList() replays the exact params of the last fetchTasks() call', async () => {
    const taskStore = useTaskStore()
    await taskStore.fetchTasks({ status: 'in_progress', priority: 'high' })
    mockTasksList.mockClear()

    await taskStore.refreshList()

    expect(mockTasksList).toHaveBeenCalledTimes(1)
    expect(mockTasksList).toHaveBeenCalledWith({ status: 'in_progress', priority: 'high' })
  })

  it('refreshList() does NOT clobber the last call into a bare paramless fetch', async () => {
    const taskStore = useTaskStore()
    await taskStore.fetchTasks({ filter_type: 'all_tasks', status: 'completed' })
    mockTasksList.mockClear()

    await taskStore.refreshList()

    // The bug this guards: a WS handler calling fetchTasks() with no args here
    // would drop filter_type/status and refetch the unfiltered default set.
    const calledWith = mockTasksList.mock.calls[0][0]
    expect(calledWith).toMatchObject({ filter_type: 'all_tasks', status: 'completed' })
  })

  it('replays the auto-added product_id scope from the last call', async () => {
    const productStore = useProductStore()
    productStore.$patch({ currentProductId: 'prod-1' })
    const taskStore = useTaskStore()
    await taskStore.fetchTasks({}) // auto-adds product_id: 'prod-1'
    mockTasksList.mockClear()

    await taskStore.refreshList()

    expect(mockTasksList).toHaveBeenCalledWith({ product_id: 'prod-1' })
  })

  it('a bare fetchTasks() with no prior call still works and is remembered', async () => {
    const taskStore = useTaskStore()
    await taskStore.refreshList() // no prior fetchTasks() call yet
    expect(mockTasksList).toHaveBeenCalledWith({})
  })
})
