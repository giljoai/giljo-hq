/**
 * websocketEventRouter.fe9538.spec.js — FE-9538
 *
 * The lifecycle-banner pass: project:staging_complete, project:implementation_launched,
 * and project_update (update_type='status_changed', status='active') each additionally
 * feed lifecycleBannerStore.announce() -- additive to the existing routing those three
 * event types already had (projectStateStore patches, debouncedRefreshList,
 * handleRealtimeUpdate), which stays byte-identical.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { EVENT_MAP, routeWebsocketEvent } from '@/stores/websocketEventRouter'
import { useLifecycleBannerStore } from '@/stores/lifecycleBannerStore'
import { useProjectStore } from '@/stores/projects'

vi.mock('@/services/api', () => {
  const projects = {
    list: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
    get: vi.fn().mockResolvedValue({ data: null }),
    getActive: vi.fn().mockResolvedValue({ data: null }),
  }
  return { api: { projects }, default: { projects } }
})

describe('websocketEventRouter — lifecycle banner pass (FE-9538)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('project:staging_complete announces a staging_complete row', async () => {
    useProjectStore().projects.push({
      id: 'proj-1',
      name: 'Fix the thing',
      taxonomy_alias: 'BE-1234',
    })

    await routeWebsocketEvent(
      { type: 'project:staging_complete', data: { project_id: 'proj-1', product_id: 'prod-1' } },
      { eventMap: EVENT_MAP },
    )

    const rows = useLifecycleBannerStore().rows
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      projectId: 'proj-1',
      moment: 'staging_complete',
      taxonomyAlias: 'BE-1234',
    })
  })

  it('project:implementation_launched announces an implementation_launched row', async () => {
    useProjectStore().projects.push({ id: 'proj-2', name: 'Ship it', taxonomy_alias: 'FE-4321' })

    await routeWebsocketEvent(
      {
        type: 'project:implementation_launched',
        data: { project_id: 'proj-2', product_id: 'prod-1' },
      },
      { eventMap: EVENT_MAP },
    )

    const rows = useLifecycleBannerStore().rows
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ projectId: 'proj-2', moment: 'implementation_launched' })
  })

  it('project_update with status_changed to active announces an activated row', async () => {
    useProjectStore().projects.push({ id: 'proj-3', name: 'Go live', taxonomy_alias: 'INF-99' })

    await routeWebsocketEvent(
      {
        type: 'project_update',
        data: { project_id: 'proj-3', update_type: 'status_changed', status: 'active' },
      },
      { eventMap: EVENT_MAP },
    )

    const rows = useLifecycleBannerStore().rows
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ projectId: 'proj-3', moment: 'activated' })
  })

  it('project_update with status_changed to a DIFFERENT status does NOT announce (not an activation)', async () => {
    useProjectStore().projects.push({ id: 'proj-4', name: 'Wrap up', taxonomy_alias: 'BE-1' })

    await routeWebsocketEvent(
      {
        type: 'project_update',
        data: { project_id: 'proj-4', update_type: 'status_changed', status: 'completed' },
      },
      { eventMap: EVENT_MAP },
    )

    expect(useLifecycleBannerStore().rows).toHaveLength(0)
  })

  it('project_update still dispatches the pre-existing handleRealtimeUpdate call (byte-identical prior behaviour)', async () => {
    const projectStore = useProjectStore()
    const spy = vi.spyOn(projectStore, 'handleRealtimeUpdate').mockResolvedValue()

    await routeWebsocketEvent(
      {
        type: 'project_update',
        data: { project_id: 'proj-5', update_type: 'status_changed', status: 'inactive' },
      },
      { eventMap: EVENT_MAP },
    )

    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        project_id: 'proj-5',
        update_type: 'status_changed',
        status: 'inactive',
      }),
    )
  })
})
