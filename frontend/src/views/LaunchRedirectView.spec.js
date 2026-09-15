import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  getActive: vi.fn(),
  replace: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  api: {
    projects: {
      getActive: (...a) => h.getActive(...a),
      get: vi.fn().mockResolvedValue({ data: { id: 'proj-9', status: 'active' } }),
      list: vi.fn().mockResolvedValue({ data: [] }),
    },
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ replace: h.replace }),
}))

import LaunchRedirectView from './LaunchRedirectView.vue'
import { routeWebsocketEvent, EVENT_MAP } from '@/stores/websocketEventRouter'
import { useProjectStore } from '@/stores/projects'

let pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

function mountView() {
  return mount(LaunchRedirectView, { global: { plugins: [pinia] } })
}

describe('LaunchRedirectView — list-shaped GET /projects/active (BE-9525a)', () => {
  it('redirects to the active project when the list has one entry', async () => {
    h.getActive.mockResolvedValue({ data: [{ id: 'proj-1' }] })

    mountView()
    await flushPromises()

    expect(h.replace).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'proj-1' },
      query: { via: 'jobs' },
    })
  })

  it('shows the empty state (does not redirect) when the list is empty', async () => {
    h.getActive.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(h.replace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Nothing in flight for this product')
  })

  it('redirects to the sectioned Jobs viewport when the list has several entries', async () => {
    h.getActive.mockResolvedValue({ data: [{ id: 'proj-1' }, { id: 'proj-2' }] })

    mountView()
    await flushPromises()

    expect(h.replace).toHaveBeenCalledWith({ name: 'JobsViewport' })
  })
})

describe('LaunchRedirectView — live activation with no reload (FE-9533)', () => {
  it('redirects once a project_update WS event activates a project, with the pane still mounted and no second fetch', async () => {
    h.getActive.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Nothing in flight for this product')
    expect(h.replace).not.toHaveBeenCalled()

    h.getActive.mockResolvedValue({ data: [{ id: 'proj-9', name: 'Headless Launch' }] })

    await routeWebsocketEvent(
      { type: 'project_update', project_id: 'proj-9', update_type: 'status_changed' },
      { eventMap: EVENT_MAP, storeRegistry: { projects: () => useProjectStore(pinia) } },
    )
    await flushPromises()

    expect(h.replace).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'proj-9' },
      query: { via: 'jobs' },
    })
    expect(h.getActive).toHaveBeenCalledTimes(2)
  })

  it('does nothing on an unrelated project_update event (no active project yet)', async () => {
    h.getActive.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    await flushPromises()

    await routeWebsocketEvent(
      { type: 'project_update', project_id: 'proj-other', update_type: 'updated' },
      { eventMap: EVENT_MAP, storeRegistry: { projects: () => useProjectStore(pinia) } },
    )
    await flushPromises()

    expect(h.replace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Nothing in flight for this product')
  })
})
