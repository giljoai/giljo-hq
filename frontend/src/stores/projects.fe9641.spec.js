import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockList = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = { projects: { list: (...a) => mockList(...a) } }
  return { api: apiMock, default: apiMock }
})

import { useProjectStore } from './projects'

const page = (from, n) => Array.from({ length: n }, (_, i) => ({ id: `p${from + i}` }))

describe('projects store: fetchAllMatchingProjects', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockList.mockReset()
  })

  it('walks every page with the same filters and leaves the visible list alone', async () => {
    mockList
      .mockResolvedValueOnce({ data: page(0, 200), headers: { 'x-total-count': '240' } })
      .mockResolvedValueOnce({ data: page(200, 40), headers: { 'x-total-count': '240' } })
    const store = useProjectStore()

    const rows = await store.fetchAllMatchingProjects({ statuses: ['inactive'], includeHidden: true, sort: 'created_at', sortDir: 'desc' })

    expect(rows).toHaveLength(240)
    expect(mockList).toHaveBeenCalledTimes(2)
    expect(mockList.mock.calls[0][0]).toMatchObject({
      statuses: ['inactive'],
      include_hidden: true,
      sort: 'created_at',
      sort_dir: 'desc',
      limit: 200,
      offset: 0,
    })
    expect(mockList.mock.calls[1][0]).toMatchObject({ limit: 200, offset: 200 })
    expect(store.projects).toHaveLength(0)
  })

  it('carries the Archived view (hidden only) through to the server', async () => {
    mockList.mockResolvedValueOnce({ data: page(0, 3), headers: { 'x-total-count': '3' } })
    const store = useProjectStore()
    await store.fetchAllMatchingProjects({ hiddenOnly: true, includeCompleted: true })
    expect(mockList.mock.calls[0][0]).toMatchObject({ hidden_only: true, include_completed: true })
  })

  it('asks nothing when no status is ticked (the list is empty too)', async () => {
    const store = useProjectStore()
    expect(await store.fetchAllMatchingProjects({ statuses: [] })).toEqual([])
    expect(mockList).not.toHaveBeenCalled()
  })
})
