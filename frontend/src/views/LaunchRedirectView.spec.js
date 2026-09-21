import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  getActive: vi.fn(),
  listRuns: vi.fn(),
  replace: vi.fn(),
}))

const mockApi = vi.hoisted(() => ({
  projects: {
    getActive: (...a) => h.getActive(...a),
    get: vi.fn().mockResolvedValue({ data: { id: 'proj-9', status: 'active' } }),
    list: vi.fn().mockResolvedValue({ data: [] }),
  },
  sequenceRuns: {
    list: (...a) => h.listRuns(...a),
  },
}))

vi.mock('@/services/api', () => ({ api: mockApi, default: mockApi }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ replace: h.replace }),
}))

import LaunchRedirectView from './LaunchRedirectView.vue'
import { routeWebsocketEvent, EVENT_MAP } from '@/stores/websocketEventRouter'
import { useProjectStore } from '@/stores/projects'
import { useProductStore } from '@/stores/products'

let pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  h.listRuns.mockResolvedValue({ data: [] })
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


describe('LaunchRedirectView — follows the viewed product tab (FE-9627)', () => {
  it('does not redirect on stale activeProjectsMeta before the scoped fetch resolves', async () => {
    const projectStore = useProjectStore(pinia)
    projectStore.activeProjectsMeta = [{ id: 'other-product-proj' }]

    let resolveFetch
    h.getActive.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve
      }),
    )

    mountView()
    await flushPromises()

    expect(h.replace).not.toHaveBeenCalled()

    resolveFetch({ data: [{ id: 'this-product-proj' }] })
    await flushPromises()

    expect(h.replace).toHaveBeenCalledTimes(1)
    expect(h.replace).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'this-product-proj' },
      query: { via: 'jobs' },
    })
  })

  it('re-fetches scoped to the new product when the tab switches', async () => {
    h.getActive.mockResolvedValue({ data: [] })

    mountView()
    await flushPromises()
    expect(h.getActive).toHaveBeenCalledTimes(1)

    const productStore = useProductStore(pinia)
    productStore.currentProductId = 'prod-b'
    await flushPromises()

    expect(h.getActive).toHaveBeenCalledTimes(2)
    expect(h.getActive).toHaveBeenLastCalledWith('prod-b')
  })
})


const STALLED_RUN = {
  id: 'run-1',
  status: 'stalled',
  resolved_order: ['member-1', 'member-2'],
  current_index: 1,
}

describe('LaunchRedirectView — resolves like the Jobs nav link (FE-9630)', () => {
  it('replaces to the active chain member when a run is in flight and no project is active', async () => {
    h.getActive.mockResolvedValue({ data: [] })
    h.listRuns.mockResolvedValue({ data: [STALLED_RUN] })

    const wrapper = mountView()
    await flushPromises()

    expect(h.replace).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'member-2' },
      query: { run: 'run-1' },
    })
    expect(wrapper.text()).not.toContain('Nothing in flight for this product')
  })

  it('resolves the same way when the operator switches INTO that product tab', async () => {
    h.getActive.mockResolvedValue({ data: [] })
    h.listRuns.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(h.replace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Nothing in flight for this product')

    h.listRuns.mockResolvedValue({ data: [STALLED_RUN] })
    const productStore = useProductStore(pinia)
    productStore.currentProductId = 'prod-b'
    await flushPromises()

    expect(h.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ product_id: 'prod-b' }))
    expect(h.replace).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'member-2' },
      query: { run: 'run-1' },
    })
  })

  it('still shows the empty state when the helper resolves to the launch page', async () => {
    h.getActive.mockResolvedValue({ data: [] })
    h.listRuns.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(h.replace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Nothing in flight for this product')
  })
})
