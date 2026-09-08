/**
 * projects store — debouncedRefreshList (Headless S3a, D1/D2/D14/D15).
 *
 * A burst of lifecycle WS events (staging complete, implementation launched,
 * the vestigial launch-project endpoint, a product-activation bulk-deactivate)
 * can each fire independently within the same headless drive. The event routes
 * call debouncedRefreshList() rather than refreshList() directly so a same-tick
 * burst collapses into ONE list refetch instead of a storm — mirroring the
 * pattern RoadmapView's onRoadmapUpdated already uses.
 *
 * Edition Scope: CE
 */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProjectStore } from '@/stores/projects'

const { mockList } = vi.hoisted(() => ({ mockList: vi.fn() }))

vi.mock('@/services/api', () => ({
  api: { projects: { list: mockList, get: vi.fn() } },
  default: { projects: { list: mockList, get: vi.fn() } },
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({ currentProductId: null }),
}))

describe('projects store — debouncedRefreshList', () => {
  let store

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    setActivePinia(createPinia())
    store = useProjectStore()
    mockList.mockResolvedValue({ data: [], headers: {} })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('collapses a same-tick burst into a single refreshList call', async () => {
    store.debouncedRefreshList()
    store.debouncedRefreshList()
    store.debouncedRefreshList()

    // Debounced: nothing fires synchronously
    expect(mockList).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1000)

    expect(mockList).toHaveBeenCalledTimes(1)
  })

  it('replays the last server-mode query, not a bare default (flash-revert guard)', async () => {
    mockList.mockResolvedValueOnce({
      data: [{ id: 'c1', status: 'completed' }],
      headers: { 'x-total-count': '1' },
    })
    await store.fetchProjects({ statuses: ['completed'], limit: 10, offset: 0 })
    mockList.mockClear()

    mockList.mockResolvedValueOnce({ data: [], headers: {} })
    store.debouncedRefreshList()
    await vi.advanceTimersByTimeAsync(1000)

    expect(mockList).toHaveBeenCalledTimes(1)
    expect(mockList.mock.calls[0][0].statuses).toEqual(['completed'])
  })
})
