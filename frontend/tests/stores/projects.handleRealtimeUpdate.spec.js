import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useProjectStore } from '@/stores/projects'
import { useProjectStateStore } from '@/stores/projectStateStore'

// FE-3007a: handleRealtimeUpdate no longer hand-copies a name/status/mission/
// description whitelist off the WS payload (the drift-prone bug factory that
// shipped two stale-state bugs). It now does full-refetch-on-event: the payload
// only says WHICH project changed, and the store re-pulls the complete entity
// from the API through its single write path. These specs assert that contract.
const mockGet = vi.fn()
const mockList = vi.fn()
const mockGetActive = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    projects: {
      get: (...a) => mockGet(...a),
      list: (...a) => mockList(...a),
      getActive: (...a) => mockGetActive(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

describe('projects store — handleRealtimeUpdate (full-refetch-on-event)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: [] })
    mockGetActive.mockResolvedValue({ data: [] })
    store = useProjectStore()
    // Seed with a known (trimmed) list row.
    store.projects = [
      {
        id: 'proj-1',
        name: 'Original Name',
        status: 'active',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
  })

  it('refetches the FULL entity on "updated" — fields the old whitelist never copied also update', async () => {
    mockGet.mockResolvedValue({
      data: {
        id: 'proj-1',
        name: 'New Name',
        description: 'New description',
        status: 'inactive',
        mission: 'New mission',
        taxonomy_alias: 'XY',
      },
    })

    // Payload carries only id + type — NONE of the entity fields.
    store.handleRealtimeUpdate({ project_id: 'proj-1', update_type: 'updated' })
    await vi.waitFor(() => expect(mockGet).toHaveBeenCalledWith('proj-1'))

    const project = store.projectById('proj-1')
    expect(project.name).toBe('New Name')
    expect(project.description).toBe('New description')
    expect(project.status).toBe('inactive')
    expect(project.mission).toBe('New mission')
    expect(project.taxonomy_alias).toBe('XY')
  })

  it('ignores payload entity fields — the API refetch is authoritative', async () => {
    mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'FROM_API', status: 'active' } })

    store.handleRealtimeUpdate({
      project_id: 'proj-1',
      update_type: 'updated',
      name: 'FROM_PAYLOAD',
      status: 'cancelled',
    })
    await vi.waitFor(() => expect(mockGet).toHaveBeenCalled())

    expect(store.projectById('proj-1').name).toBe('FROM_API')
    expect(store.projectById('proj-1').status).toBe('active')
  })

  it('refetches once per event (single GET, single write path)', async () => {
    mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'X', status: 'completed' } })

    store.handleRealtimeUpdate({ project_id: 'proj-1', update_type: 'closed' })
    await vi.waitFor(() => expect(mockGet).toHaveBeenCalled())

    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(store.projectById('proj-1').status).toBe('completed')
  })

  it.each(['status_changed', 'activated', 'deactivated', 'closed', 'updated'])(
    'refetches the entity for update_type "%s"',
    async (update_type) => {
      mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'n', status: 'inactive' } })

      store.handleRealtimeUpdate({ project_id: 'proj-1', update_type })
      await vi.waitFor(() => expect(mockGet).toHaveBeenCalledWith('proj-1'))

      expect(mockGet).toHaveBeenCalledTimes(1)
    },
  )

  it('handles update_type "created" — refreshes the list, no per-id GET', async () => {
    mockList.mockResolvedValue({
      data: [
        { id: 'proj-1', name: 'Original Name', status: 'active' },
        { id: 'proj-new', name: 'New Project', status: 'active' },
      ],
    })

    store.handleRealtimeUpdate({ project_id: 'proj-new', update_type: 'created' })
    await vi.waitFor(() => expect(mockList).toHaveBeenCalled())

    expect(mockGet).not.toHaveBeenCalled()
    expect(store.projects).toHaveLength(2)
    expect(store.projectById('proj-new').name).toBe('New Project')
  })

  it('ignores events with no project_id (no fetch, no crash)', () => {
    store.handleRealtimeUpdate({ update_type: 'updated', name: 'Ghost' })
    expect(mockGet).not.toHaveBeenCalled()
    expect(mockList).not.toHaveBeenCalled()
    expect(store.projects).toHaveLength(1)
  })

  it('refetches a not-yet-cached project too (detail-page deep link)', async () => {
    // An "updated" event for a project not in the list still pulls the complete
    // entity into byId (store writer COMPLETE) — it does NOT pollute the list.
    mockGet.mockResolvedValue({ data: { id: 'proj-x', name: 'Deep', status: 'active' } })

    store.handleRealtimeUpdate({ project_id: 'proj-x', update_type: 'updated' })
    await vi.waitFor(() => expect(mockGet).toHaveBeenCalledWith('proj-x'))

    expect(store.projectById('proj-x')).toMatchObject({ name: 'Deep' })
    expect(store.projects).toHaveLength(1) // unchanged list
  })

  // FE-9510 — LOAD-BEARING REGRESSION: a project deleted by another client (or
  // the QA harness) broadcasts a plain "updated"-shaped project_update. The old
  // code refetched and PATCHED the existing list row in place — a soft-deleted
  // project has status 'deleted' but the entity still exists, so it never left
  // the list. It must leave, immediately, without a page refresh.
  it('removes the list row when the refetched status is "deleted" (FE-9510)', async () => {
    store.projects = [
      { id: 'proj-1', name: 'Original Name', status: 'active', updated_at: '2026-01-01T00:00:00Z' },
    ]
    mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'Original Name', status: 'deleted' } })

    await store.handleRealtimeUpdate({ project_id: 'proj-1', update_type: 'updated' })

    // Assert the STORE's list contents — a test against the endpoint would be
    // green on broken code (the endpoint already excludes deleted correctly).
    expect(store.projects.find((p) => p.id === 'proj-1')).toBeUndefined()
    expect(store.projects).toHaveLength(0)
    // byId still resolves — a detail view/deep-link must not 404.
    expect(store.projectById('proj-1')).toMatchObject({ status: 'deleted' })
  })

  it('removes the list row when the refetched status is "superseded" (FE-9510)', async () => {
    store.projects = [
      { id: 'proj-1', name: 'Original Name', status: 'active', updated_at: '2026-01-01T00:00:00Z' },
    ]
    mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'Original Name', status: 'superseded' } })

    await store.handleRealtimeUpdate({ project_id: 'proj-1', update_type: 'updated' })

    expect(store.projects.find((p) => p.id === 'proj-1')).toBeUndefined()
    expect(store.projects).toHaveLength(0)
    expect(store.projectById('proj-1')).toMatchObject({ status: 'superseded' })
  })

  it('leaves other rows in place when removing a deleted row (FE-9510)', async () => {
    store.projects = [
      { id: 'proj-1', name: 'Deleted Me', status: 'active', updated_at: '2026-01-01T00:00:00Z' },
      { id: 'proj-2', name: 'Still Here', status: 'active', updated_at: '2026-01-01T00:00:00Z' },
    ]
    mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'Deleted Me', status: 'deleted' } })

    await store.handleRealtimeUpdate({ project_id: 'proj-1', update_type: 'updated' })

    expect(store.projects.map((p) => p.id)).toEqual(['proj-2'])
  })

  // FE-9122 — LOAD-BEARING REGRESSION: the multi-client / MCP-driven case the
  // old setExecutionMode() bandage never covered. A SECOND browser (or any
  // client that didn't itself click the mode radio) receives the SAME
  // project_update broadcast and must see the fresh execution_mode too — the
  // single _upsertEntity write path must hydrate projectStateStore, not just
  // projects.byId, on every refetch.
  it('bridges the refetched entity into projectStateStore (FE-9122)', async () => {
    mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'Original Name', execution_mode: 'subagent' } })

    store.handleRealtimeUpdate({ project_id: 'proj-1', update_type: 'updated' })
    await vi.waitFor(() => expect(mockGet).toHaveBeenCalledWith('proj-1'))

    const projectStateStore = useProjectStateStore()
    expect(projectStateStore.getProjectState('proj-1')?.execution_mode).toBe('subagent')
  })

  // FE-9533 — LOAD-BEARING REGRESSION: activeProjectMeta (the dedicated
  // /projects/active read consumed by LaunchRedirectView's Jobs pane and by
  // ProjectsView's hasActiveProject) was written ONLY from the two local,
  // self-triggered actions (activateProject/deactivateProject). A project
  // activated from ANOTHER session or headlessly over MCP broadcasts the same
  // project_update/status_changed event this whole file already asserts
  // refetches the entity — but the entity refetch alone never touches
  // activeProjectMeta, so a client that never separately re-ran
  // fetchActiveProject() (e.g. the Jobs pane, which historically bypassed the
  // store) stayed stuck on stale activation state until a manual reload. The
  // fix: a status_changed event also re-derives activeProjectMeta from the
  // authoritative /projects/active read, the SAME live mechanism the Projects
  // list already uses for its own fields.
  it('refreshes activeProjectMeta on a "status_changed" event for a project not yet in the list (FE-9533)', async () => {
    // Deliberately proj-2 is NOT seeded into store.projects — this is the Jobs
    // pane's real starting condition (it never fetches the paginated list at
    // all), not the Projects-list page's condition.
    mockGet.mockResolvedValue({ data: { id: 'proj-2', name: 'Activated Elsewhere', status: 'active' } })
    mockGetActive.mockResolvedValue({ data: [{ id: 'proj-2', name: 'Activated Elsewhere' }] })

    expect(store.activeProjectMeta).toBeNull()

    store.handleRealtimeUpdate({ project_id: 'proj-2', update_type: 'status_changed' })

    await vi.waitFor(() => expect(mockGetActive).toHaveBeenCalled())
    expect(store.activeProjectMeta).toMatchObject({ id: 'proj-2', name: 'Activated Elsewhere' })
  })

  it('refreshes activeProjectMeta to null on a "status_changed" deactivation event', async () => {
    store.activeProjectMeta = { id: 'proj-1', name: 'Original Name' }
    mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'Original Name', status: 'inactive' } })
    mockGetActive.mockResolvedValue({ data: [] })

    store.handleRealtimeUpdate({ project_id: 'proj-1', update_type: 'status_changed' })

    await vi.waitFor(() => expect(mockGetActive).toHaveBeenCalled())
    expect(store.activeProjectMeta).toBeNull()
  })

  it('does NOT refresh activeProjectMeta on a non-status update_type (no extra request)', async () => {
    mockGet.mockResolvedValue({ data: { id: 'proj-1', name: 'New Name', status: 'active' } })

    store.handleRealtimeUpdate({ project_id: 'proj-1', update_type: 'updated' })
    await vi.waitFor(() => expect(mockGet).toHaveBeenCalled())

    expect(mockGetActive).not.toHaveBeenCalled()
  })
})
