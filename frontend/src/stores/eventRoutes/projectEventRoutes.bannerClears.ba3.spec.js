import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/api', () => {
  const apiMock = { projects: { list: vi.fn(), get: vi.fn() } }
  return { api: apiMock, default: apiMock }
})

import { PROJECT_EVENT_ROUTES } from './projectEventRoutes'
import { useLifecycleBannerStore } from '../lifecycleBannerStore'
import { useProjectStore } from '../projects'
import { useSettingsStore } from '../settings'

const route = PROJECT_EVENT_ROUTES.project_update.handler

describe('lifecycle notice clears when its project is no longer running', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useProjectStore().handleRealtimeUpdate = vi.fn().mockResolvedValue(undefined)
    useSettingsStore().bannerLifecycleEnabled = true
  })

  it.each(['completed', 'terminated', 'cancelled', 'parked', 'deleted'])('status %s removes that project\'s notice', async (status) => {
    const banner = useLifecycleBannerStore()
    banner.announce({ projectId: 'p1', moment: 'implementation_launched' })
    banner.announce({ projectId: 'p2', moment: 'implementation_launched' })
    expect(banner.rows).toHaveLength(2)
    await route({ project_id: 'p1', update_type: 'status_changed', status })
    expect(banner.rows.map((r) => r.projectId)).toEqual(['p2'])
  })

  it('a still-running status leaves the notice alone', async () => {
    const banner = useLifecycleBannerStore()
    banner.announce({ projectId: 'p1', moment: 'implementation_launched' })
    await route({ project_id: 'p1', update_type: 'status_changed', status: 'active' })
    expect(banner.rows).toHaveLength(1)
  })

  it('a payload without a project id does nothing', async () => {
    const banner = useLifecycleBannerStore()
    banner.announce({ projectId: 'p1', moment: 'implementation_launched' })
    await route({ update_type: 'status_changed', status: 'completed' })
    expect(banner.rows).toHaveLength(1)
  })
})
