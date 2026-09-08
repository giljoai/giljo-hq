/**
 * LaunchRedirectView.spec.js — BE-9525a, FE-9533
 *
 * BE-9525a: GET /api/v1/projects/active became list-shaped (plural-ready ahead
 * of BE-9525b). An empty array is truthy in JS, so the old `if (response.data)`
 * check would have redirected to a launch route with `projectId: undefined`
 * even when no project is active, instead of showing the "No Active Project"
 * page.
 *
 * FE-9533: the view used to call api.projects.getActive() directly into a
 * local ref, bypassing the projects store entirely — a one-shot read with no
 * path back to the DOM when a project became active from another session, or
 * headlessly over MCP, while the operator sat on "No Active Project". It now
 * reads the store's `activeProjectMeta`, which the store's own WS handler
 * (handleRealtimeUpdate, see tests/stores/projects.handleRealtimeUpdate.spec.js)
 * keeps live. The tests below drive that through the REAL pinia store and the
 * REAL websocket event router — not by calling the store action or the fetch
 * directly — to prove the actual WS event reaches the DOM with no reload.
 *
 * Each test gets its OWN Pinia instance passed explicitly to `mount()`'s
 * `global.plugins` (tests/setup.js installs one shared file-level Pinia into
 * `config.global.plugins` for every mount by default — sharing it across
 * these tests would leak `activeProjectMeta` state between them).
 *
 * Edition scope: Both.
 */
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
      // FE-9533: handleRealtimeUpdate's full-refetch-on-event path calls these
      // too (see tests/stores/projects.handleRealtimeUpdate.spec.js for the
      // dedicated contract tests) — stubbed here just to keep this file's WS
      // dispatch quiet, not under test.
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

  // FE-9525d: BE-9525a/b retired the single-active-project-per-product
  // invariant, so this list can genuinely hold more than one row now.
  it('redirects to the sectioned Jobs viewport when the list has several entries', async () => {
    h.getActive.mockResolvedValue({ data: [{ id: 'proj-1' }, { id: 'proj-2' }] })

    mountView()
    await flushPromises()

    expect(h.replace).toHaveBeenCalledWith({ name: 'JobsViewport' })
  })
})

describe('LaunchRedirectView — live activation with no reload (FE-9533)', () => {
  it('redirects once a project_update WS event activates a project, with the pane still mounted and no second fetch', async () => {
    // Nothing active yet — the pane renders the empty state, matching the
    // reported symptom's starting state.
    h.getActive.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Nothing in flight for this product')
    expect(h.replace).not.toHaveBeenCalled()

    // A project becomes active elsewhere (another session, or headlessly over
    // MCP) and the backend broadcasts the real event shape
    // (project_lifecycle_service.activate_project -> broadcast_project_update
    // with update_type="status_changed"). Drive it through the ACTUAL router
    // pipeline the app wires up in production (routeWebsocketEvent + the real
    // EVENT_MAP), not by calling projectStore.fetchActiveProject() or
    // handleRealtimeUpdate() directly — this is the event, not the fetch.
    // storeRegistry resolves to THIS test's own pinia (same instance the
    // mounted view uses), matching how the app's singleton router/store wiring
    // behaves at runtime.
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
    // The mount-time fetch, plus the ONE re-derive the event triggered inside
    // the store's handleRealtimeUpdate — the view itself never re-fetches.
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
