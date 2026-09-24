/**
 * Regression tests for IMP-1002 status-filter fix:
 *
 * 1. fetchProjects({ includeCompleted: true }) must pass include_completed=true
 *    to the API — ensures finished-status rows are fetched from the server.
 *
 * 2. fetchProjects() with no args must NOT pass any status param — preserves
 *    the backend default (active+inactive only, the perf win).
 *
 * 3. fetchProjects({ statusFilter: 'completed' }) must pass status_filter=completed.
 *
 * Edition Scope: CE
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProjectStore } from '@/stores/projects'

// ── mocks ──────────────────────────────────────────────────────────────────────

const { mockList } = vi.hoisted(() => ({
  mockList: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  api: {
    projects: {
      list: mockList,
      get: vi.fn(),
      activate: vi.fn(),
      deactivate: vi.fn(),
    },
  },
  default: {
    projects: {
      list: mockList,
      get: vi.fn(),
      activate: vi.fn(),
      deactivate: vi.fn(),
    },
  },
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({ currentProductId: 'prod-1' }),
}))

// ── fixtures ───────────────────────────────────────────────────────────────────

const COMPLETED_PROJ = {
  id: 'proj-c',
  name: 'Done Deal',
  status: 'completed',
  product_id: 'prod-1',
}
const ACTIVE_PROJ = {
  id: 'proj-a',
  name: 'In Flight',
  status: 'active',
  product_id: 'prod-1',
}

// ── suite ──────────────────────────────────────────────────────────────────────

describe('projects store — IMP-1002 status-filter re-fetch params', () => {
  let store

  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    store = useProjectStore()
  })

  // ────────────────────────────────────────────────────────────────────────────
  // 1. Default fetch — no extra params
  // ────────────────────────────────────────────────────────────────────────────
  it('fetchProjects() sends only product_id — no status_filter or include_completed', async () => {
    mockList.mockResolvedValueOnce({ data: [ACTIVE_PROJ] })

    await store.fetchProjects()

    expect(mockList).toHaveBeenCalledOnce()
    const params = mockList.mock.calls[0][0]
    expect(params).toHaveProperty('product_id', 'prod-1')
    expect(params).not.toHaveProperty('include_completed')
    expect(params).not.toHaveProperty('status_filter')
  })

  // ────────────────────────────────────────────────────────────────────────────
  // 2. includeCompleted=true — must send include_completed=true
  // ────────────────────────────────────────────────────────────────────────────
  it('fetchProjects({ includeCompleted: true }) sends include_completed=true', async () => {
    mockList.mockResolvedValueOnce({ data: [ACTIVE_PROJ, COMPLETED_PROJ] })

    await store.fetchProjects({ includeCompleted: true })

    expect(mockList).toHaveBeenCalledOnce()
    const params = mockList.mock.calls[0][0]
    expect(params).toHaveProperty('include_completed', true)
    expect(params).not.toHaveProperty('status_filter')
  })

  // ────────────────────────────────────────────────────────────────────────────
  // 3. statusFilter — must send status_filter=<value>
  // ────────────────────────────────────────────────────────────────────────────
  it('fetchProjects({ statusFilter: "completed" }) sends status_filter=completed', async () => {
    mockList.mockResolvedValueOnce({ data: [COMPLETED_PROJ] })

    await store.fetchProjects({ statusFilter: 'completed' })

    expect(mockList).toHaveBeenCalledOnce()
    const params = mockList.mock.calls[0][0]
    expect(params).toHaveProperty('status_filter', 'completed')
    expect(params).not.toHaveProperty('include_completed')
  })

  // ────────────────────────────────────────────────────────────────────────────
  // 4. Store is populated with the server response
  // ────────────────────────────────────────────────────────────────────────────
  it('fetchProjects({ includeCompleted: true }) populates store with all returned rows', async () => {
    mockList.mockResolvedValueOnce({ data: [ACTIVE_PROJ, COMPLETED_PROJ] })

    await store.fetchProjects({ includeCompleted: true })

    expect(store.projects).toHaveLength(2)
    expect(store.projects.map((p) => p.status)).toContain('completed')
    expect(store.projects.map((p) => p.status)).toContain('active')
  })

  // ────────────────────────────────────────────────────────────────────────────
  // 5. Out-of-order response guard (the hard-refresh status-filter race).
  //
  // Repro: onMounted fires the default (active+inactive) fetch; while it is
  // still in flight the user selects "Completed", firing the include_completed
  // fetch. If the slower DEFAULT response lands LAST it must NOT clobber the
  // newer full-set response — otherwise completed/cancelled rows silently
  // vanish (the exact symptom: shows after navigate-back, empty after refresh).
  // ────────────────────────────────────────────────────────────────────────────
  it('a stale default fetch resolving after a newer full-set fetch does not overwrite it', async () => {
    // Deferred promises so we control resolution order.
    let resolveDefault
    let resolveFull
    const defaultResponse = new Promise((r) => {
      resolveDefault = r
    })
    const fullResponse = new Promise((r) => {
      resolveFull = r
    })

    // First call (default, dispatched first) gets the slow promise;
    // second call (full set) gets the other.
    mockList.mockReturnValueOnce(defaultResponse)
    mockList.mockReturnValueOnce(fullResponse)

    // Dispatch both without awaiting — mirrors onMounted + watch racing.
    const p1 = store.fetchProjects() // seq 1 (default)
    const p2 = store.fetchProjects({ includeCompleted: true }) // seq 2 (full set)

    // Newer full-set response lands first…
    resolveFull({ data: [ACTIVE_PROJ, COMPLETED_PROJ] })
    // …then the OLDER default response lands last (the dangerous ordering).
    resolveDefault({ data: [ACTIVE_PROJ] })

    await Promise.all([p1, p2])

    // The latest dispatched fetch (seq 2) wins; the stale seq-1 response is dropped.
    expect(store.projects).toHaveLength(2)
    expect(store.projects.map((p) => p.status)).toContain('completed')
  })

  // ────────────────────────────────────────────────────────────────────────────
  // 6. The other half of the same race: the NEWER fetch FAILS.
  //
  // The seq guard above drops an older response because a newer one was
  // dispatched. It must not drop it because a newer one was dispatched and then
  // came back empty-handed: a refused request (a 429 under a saturated rate
  // limiter, an offline blip) applies nothing, so discarding the good older
  // payload leaves the list showing whatever it held before -- indefinitely,
  // because nothing refetches. Newer data must beat older data; NO data must
  // beat neither.
  // ────────────────────────────────────────────────────────────────────────────
  it('an older fetch still applies when the newer fetch that superseded it fails', async () => {
    let resolveFirst
    let rejectSecond
    const firstResponse = new Promise((r) => {
      resolveFirst = r
    })
    const secondResponse = new Promise((_r, reject) => {
      rejectSecond = reject
    })

    mockList.mockReturnValueOnce(firstResponse)
    mockList.mockReturnValueOnce(secondResponse)

    const p1 = store.fetchProjects({ includeCompleted: true }) // seq 1
    const p2 = store.fetchProjects({ includeCompleted: true }) // seq 2, supersedes it

    // The newer request is refused, so it never has a payload to apply...
    rejectSecond(new Error('Request failed with status code 429'))
    // ...and only then does the older, still-valid response land.
    resolveFirst({ data: [ACTIVE_PROJ, COMPLETED_PROJ] })

    await Promise.all([p1, p2])

    expect(store.projects).toHaveLength(2)
    expect(store.projects.map((p) => p.status)).toContain('completed')
  })

  // ────────────────────────────────────────────────────────────────────────────
  // 7. The empty multi-select short-circuit applies a payload too.
  //
  // Unticking every status empties the list without issuing a request. That is
  // still an applied result, so a slower fetch dispatched BEFORE it must not
  // land afterwards and refill the list the user just emptied.
  // ────────────────────────────────────────────────────────────────────────────
  it('an in-flight older fetch does not refill a list the empty multi-select just cleared', async () => {
    let resolveSlow
    mockList.mockReturnValueOnce(
      new Promise((r) => {
        resolveSlow = r
      })
    )

    const slow = store.fetchProjects({ includeCompleted: true }) // seq 1, in flight
    const cleared = store.fetchProjects({ statuses: [] }) // seq 2, applies [] with no request

    resolveSlow({ data: [ACTIVE_PROJ, COMPLETED_PROJ] })
    await Promise.all([slow, cleared])

    expect(store.projects).toHaveLength(0)
  })
})
