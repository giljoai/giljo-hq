import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockGet = vi.fn()
const mockList = vi.fn()
const mockUpdate = vi.fn()
const mockGetActive = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    projects: {
      get: (...a) => mockGet(...a),
      list: (...a) => mockList(...a),
      update: (...a) => mockUpdate(...a),
      getActive: (...a) => mockGetActive(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

import { useProjectStore } from './projects'
import { useProductStore } from '@/stores/products'

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
    expect(store.projects).toHaveLength(0)
    expect(store.projectById('p1')).toMatchObject({
      name: 'Detail',
      description: 'full',
      mission: 'm',
      taxonomy_alias: 'XY',
    })
  })

  it('projectById prefers the complete byId entity over a trimmed list row', async () => {
    const store = useProjectStore()
    store.projects.push({ id: 'p1', name: 'List Row', status: 'active' })
    expect(store.projectById('p1').description).toBeUndefined()

    mockGet.mockResolvedValue({
      data: { id: 'p1', name: 'List Row', status: 'active', description: 'full', mission: 'm' },
    })
    await store.fetchProject('p1')

    const entity = store.projectById('p1')
    expect(entity.description).toBe('full')
    expect(entity.mission).toBe('m')
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

  it('fetchHiddenProjects lists hidden rows via hidden_only + include_completed', async () => {
    const store = useProjectStore()
    mockList.mockResolvedValue({ data: [{ id: 'h1', name: 'Hidden', status: 'active', hidden: true }] })

    await store.fetchHiddenProjects()

    const params = mockList.mock.calls.at(-1)[0]
    expect(params.hidden_only).toBe(true)
    expect(params.include_completed).toBe(true)
    expect(store.hiddenProjects).toHaveLength(1)
    expect(store.hiddenProjects[0].id).toBe('h1')
    expect(store.projects).toHaveLength(0)
  })

  const REST_LIMIT_MAX = 200

  it('fetchSuccessorCandidates sends a limit within the REST endpoint bound (or omits it)', async () => {
    const store = useProjectStore()
    mockList.mockResolvedValue({ data: [] })

    await store.fetchSuccessorCandidates('proj-self')

    const params = mockList.mock.calls.at(-1)[0]
    expect(params.limit === undefined || params.limit <= REST_LIMIT_MAX).toBe(true)
    expect(params.statuses).toEqual(['active', 'completed', 'inactive'])
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

  it('fetchSuccessorCandidates requests inactive projects as eligible successors', async () => {
    const store = useProjectStore()
    mockList.mockResolvedValue({ data: [] })

    await store.fetchSuccessorCandidates('proj-self')

    const params = mockList.mock.calls.at(-1)[0]
    expect(params.statuses).toContain('inactive')
    expect(params.statuses).not.toContain('cancelled')
    expect(params.statuses).not.toContain('terminated')
    expect(params.statuses).not.toContain('deleted')
    expect(params.statuses).not.toContain('superseded')
  })

  describe('fetchActiveProject — per-product scoping (BE-9525a)', () => {
    it('scopes the read to the viewed product via effectiveProductId', async () => {
      const store = useProjectStore()
      const productStore = useProductStore()
      productStore.currentProductId = 'product-b'
      mockGetActive.mockResolvedValue({ data: [] })

      await store.fetchActiveProject()

      expect(mockGetActive).toHaveBeenCalledWith('product-b', true)
    })

    it('consumes the list response shape, taking the first entry', async () => {
      const store = useProjectStore()
      mockGetActive.mockResolvedValue({ data: [{ id: 'p1', status: 'active' }] })

      await store.fetchActiveProject()

      expect(store.activeProjectsMeta).toEqual([{ id: 'p1', status: 'active' }])
    })

    it('splits completed-unreviewed projects out of the in-flight list', async () => {
      const store = useProjectStore()
      mockGetActive.mockResolvedValue({
        data: [
          { id: 'live', status: 'active' },
          { id: 'done', status: 'completed', review_pending: true },
        ],
      })

      await store.fetchActiveProject()

      expect(store.activeProjectsMeta.map((p) => p.id)).toEqual(['live'])
      expect(store.unreviewedProjectsMeta.map((p) => p.id)).toEqual(['done'])
    })

    it('clears activeProjectsMeta when the list is empty (no active project in scope)', async () => {
      const store = useProjectStore()
      mockGetActive.mockResolvedValue({ data: [] })

      await store.fetchActiveProject()

      expect(store.activeProjectsMeta).toEqual([])
    })
  })
})
