import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/api', () => {
  const apiMock = { projects: { list: vi.fn(), get: vi.fn() } }
  return { api: apiMock, default: apiMock }
})

import { PROJECT_EVENT_ROUTES } from './projectEventRoutes'
import { useProjectStateStore } from '../projectStateStore'
import { useLifecycleBannerStore } from '../lifecycleBannerStore'
import { useProjectStore } from '../projects'

describe('projectEventRoutes: store faults surface', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useProjectStore().debouncedRefreshList = vi.fn()
  })

  it('a throwing state-store handler rejects the staging_complete route', async () => {
    useProjectStateStore().handleStagingComplete = () => {
      throw new Error('state store fault')
    }
    await expect(
      PROJECT_EVENT_ROUTES['project:staging_complete'].handler({ project_id: 'p1' }),
    ).rejects.toThrow('state store fault')
  })

  it('a throwing banner store rejects the implementation_launched route', async () => {
    useLifecycleBannerStore().announce = () => {
      throw new Error('banner fault')
    }
    await expect(
      PROJECT_EVENT_ROUTES['project:implementation_launched'].handler({ project_id: 'p1' }),
    ).rejects.toThrow('banner fault')
  })
})
