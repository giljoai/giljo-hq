/**
 * projects.spec.js — FE-3007a
 *
 * The project store is the single normalized owner of the project ENTITY,
 * keyed by id. These specs prove the ENTITY-OWNERSHIP half of FE-3007a:
 *   - fetchProject upserts the complete entity into byId even when the project
 *     is not in the trimmed list array (store writer COMPLETE), without
 *     polluting list views with detail-only entities.
 *   - projectById prefers the complete byId entity over a trimmed list row.
 *   - a single write path (_upsertEntity) feeds both byId and the list row.
 *
 * The full-refetch-on-event WS contract is proven in
 * tests/stores/projects.handleRealtimeUpdate.spec.js.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockGet = vi.fn()
const mockList = vi.fn()
const mockUpdate = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    projects: {
      get: (...a) => mockGet(...a),
      list: (...a) => mockList(...a),
      update: (...a) => mockUpdate(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

import { useProjectStore } from './projects'

describe('projects store — FE-3007a normalized entity owner (byId)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: [] })
  })

  it('fetchProject stores the complete entity by id even when not in the list', async () => {
    const store = useProjectStore()
    expect(store.projects).toHaveLength(0)

    mockGet.mockResolvedValue({
      data: { id: 'p1', name: 'Detail', description: 'full', mission: 'm', taxonomy_alias: 'XY' },
    })

    const result = await store.fetchProject('p1')

    expect(result.id).toBe('p1')
    // Not injected into the trimmed list array (no pollution of list views)…
    expect(store.projects).toHaveLength(0)
    // …but addressable as the complete entity by id.
    expect(store.projectById('p1')).toMatchObject({
      name: 'Detail',
      description: 'full',
      mission: 'm',
      taxonomy_alias: 'XY',
    })
  })

  it('projectById prefers the complete byId entity over a trimmed list row', async () => {
    const store = useProjectStore()
    // Seed a trimmed list row (no description/mission — ProjectListResponse).
    store.projects.push({ id: 'p1', name: 'List Row', status: 'active' })
    expect(store.projectById('p1').description).toBeUndefined()

    mockGet.mockResolvedValue({
      data: { id: 'p1', name: 'List Row', status: 'active', description: 'full', mission: 'm' },
    })
    await store.fetchProject('p1')

    const entity = store.projectById('p1')
    expect(entity.description).toBe('full')
    expect(entity.mission).toBe('m')
    // The list row is kept in sync too (single write path feeds both).
    expect(store.projects[0].description).toBe('full')
  })

  it('updateProject writes through the single path (byId + list row stay in sync)', async () => {
    const store = useProjectStore()
    store.projects.push({ id: 'p1', name: 'old', status: 'active' })

    mockUpdate.mockResolvedValue({ data: { id: 'p1', name: 'edited', status: 'active', description: 'd' } })
    await store.updateProject('p1', { name: 'edited' })

    expect(store.projectById('p1').name).toBe('edited')
    expect(store.projectById('p1').description).toBe('d')
    expect(store.projects[0].name).toBe('edited')
  })

  // BE-6078: the "Show hidden" view fetches hidden rows via the server-side
  // offload params (hidden_only + include_completed) into a separate array — it
  // is a pure read (never re-tags) and never pollutes the visible list.
  it('fetchHiddenProjects lists hidden rows via hidden_only + include_completed', async () => {
    const store = useProjectStore()
    mockList.mockResolvedValue({ data: [{ id: 'h1', name: 'Hidden', status: 'active', hidden: true }] })

    await store.fetchHiddenProjects()

    const params = mockList.mock.calls.at(-1)[0]
    expect(params.hidden_only).toBe(true)
    expect(params.include_completed).toBe(true)
    expect(store.hiddenProjects).toHaveLength(1)
    expect(store.hiddenProjects[0].id).toBe('h1')
    // The visible list is untouched (no pollution from the hidden view).
    expect(store.projects).toHaveLength(0)
  })

  // FE-9485: GET /api/v1/projects/ validates limit with `le=200` (BE-6076's
  // deliberate page-size bound — see api/endpoints/projects/crud.py). The
  // Supersede picker's candidate fetch must stay inside that bound or the
  // backend 422s and the dialog can never load. Per crud.py's own docstring,
  // omitting `limit` returns the full set, which is what the picker needs.
  const REST_LIMIT_MAX = 200

  it('fetchSuccessorCandidates sends a limit within the REST endpoint bound (or omits it)', async () => {
    const store = useProjectStore()
    mockList.mockResolvedValue({ data: [] })

    await store.fetchSuccessorCandidates('proj-self')

    const params = mockList.mock.calls.at(-1)[0]
    expect(params.limit === undefined || params.limit <= REST_LIMIT_MAX).toBe(true)
    expect(params.statuses).toEqual(['active', 'completed'])
  })

  it('fetchSuccessorCandidates excludes the project being superseded from the result', async () => {
    const store = useProjectStore()
    mockList.mockResolvedValue({
      data: [
        { id: 'proj-self', name: 'Self' },
        { id: 'proj-other', name: 'Other' },
      ],
    })

    const result = await store.fetchSuccessorCandidates('proj-self')

    expect(result).toEqual([{ id: 'proj-other', name: 'Other' }])
  })
})
