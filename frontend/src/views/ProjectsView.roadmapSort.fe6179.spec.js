/**
 * ProjectsView.roadmapSort.fe6179.spec.js — FE-6179
 *
 * Regression test at the FE wiring layer for the roadmap-order sort button on
 * /projects. The projects list is server-paginated (BE-6076): the sort is done
 * in SQL, driven by the `sort`/`sortDir` query params the view sends. The
 * roadmap-icon toolbar button must:
 *   - use the SAME icon the navbar uses for /roadmap (mdi-map-marker-path), so it
 *     reads as "roadmap order";
 *   - flip the server sort key to 'roadmap' (the repository then orders by each
 *     project's roadmap_items.sort_order — the SAME single source /roadmap
 *     renders; backend ordering proven in
 *     tests/services/test_be6076_projects_list_pagination.py);
 *   - reset to page 1 and re-fetch on toggle;
 *   - toggle OFF back to the default newest-first order (must-sort forbids an
 *     empty sort, so "off" is the default sort, not no sort).
 *
 * Asserts the entry point only — that the button drives `sort=roadmap` through
 * fetchProjects. The actual roadmap ordering is asserted server-side.
 *
 * Edition scope: CE.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

// The navbar's Roadmap entry icon (NavigationDrawer.vue: { name: 'Roadmap',
// path: '/roadmap', icon: 'mdi-map-marker-path' }). The button MUST reuse it.
const ROADMAP_ICON = 'mdi-map-marker-path'

const h = vi.hoisted(() => ({
  fetchProjects: vi.fn().mockResolvedValue(undefined),
  fetchActiveProject: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, storeToRefs: (s) => ({ statuses: s.statuses }) }
})

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/sequenceRunStore', () => ({
  useSequenceRunStore: () => ({
    activeChainProjectIds: [],
    isProjectInActiveChain: vi.fn().mockReturnValue(false),
    isProjectRunLocked: vi.fn().mockReturnValue(false),
    runForProject: vi.fn().mockReturnValue(null),
    hydrate: vi.fn().mockResolvedValue(undefined),
  }),
}))
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    projects: [],
    projectsTotal: 0,
    loading: false,
    deletedProjects: [],
    hiddenProjects: [],
    activeProjectMeta: null,
    fetchProjects: h.fetchProjects,
    fetchActiveProject: h.fetchActiveProject,
    fetchHiddenProjects: vi.fn().mockResolvedValue(undefined),
    fetchDeletedProjects: vi.fn().mockResolvedValue(undefined),
    fetchProject: vi.fn().mockResolvedValue(null),
    clearListQuery: vi.fn(),
  }),
}))
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    // FE-9502c: ProjectsView now scopes by the viewed tab (currentProduct),
    // not the server's single activeProduct.
    currentProduct: { id: 'prod-1' },
    activeProduct: { id: 'prod-1' },
    fetchProducts: vi.fn().mockResolvedValue(undefined),
    fetchActiveProduct: vi.fn().mockResolvedValue(undefined),
  }),
}))
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ clearForProject: vi.fn() }),
}))
vi.mock('@/stores/projectStatusesStore', () => ({
  useProjectStatusesStore: () => ({
    statuses: ref([]),
    ensureLoaded: vi.fn().mockResolvedValue(undefined),
  }),
}))
vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: vi.fn(() => vi.fn()),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/services/api', () => ({
  default: {
    taxonomyTypes: { list: vi.fn().mockResolvedValue({ data: [] }) },
  },
}))

import ProjectsView from './ProjectsView.vue'

async function mountView() {
  const wrapper = mount(ProjectsView, {
    shallow: true,
    global: { renderStubDefaultSlot: true },
  })
  await flushPromises() // let onMounted's initial fetchPage settle
  // onMounted fires the first fetchProjects (default created_at sort); clear so
  // assertions reflect ONLY what the button triggers.
  h.fetchProjects.mockClear()
  return wrapper
}

function lastSortParams() {
  const calls = h.fetchProjects.mock.calls
  return calls[calls.length - 1]?.[0] || {}
}

describe('ProjectsView roadmap-order sort (FE-6179)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('button reuses the navbar Roadmap icon (mdi-map-marker-path)', async () => {
    const wrapper = await mountView()
    const btn = wrapper.find('.filter-cta-roadmap')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('icon')).toBe(ROADMAP_ICON)
  })

  it('defaults to newest-first; roadmap sort inactive at mount', async () => {
    const wrapper = await mountView()
    expect(wrapper.vm.roadmapSortActive).toBe(false)
    expect(wrapper.vm.sortBy[0]).toEqual({ key: 'created_at', order: 'desc' })
  })

  it('toggle ON -> server sort key becomes "roadmap", page resets, re-fetches', async () => {
    const wrapper = await mountView()

    wrapper.vm.toggleRoadmapSort()
    await flushPromises()

    expect(wrapper.vm.roadmapSortActive).toBe(true)
    expect(wrapper.vm.sortBy[0]).toEqual({ key: 'roadmap', order: 'asc' })
    expect(wrapper.vm.currentPage).toBe(1)
    // The roadmap order is carried to the server as sort=roadmap (the SAME
    // ordering source /roadmap uses — no second ordering invented client-side).
    const params = lastSortParams()
    expect(params.sort).toBe('roadmap')
    expect(params.sortDir).toBe('asc')
  })

  it('toggle OFF -> reverts to the default newest-first server sort', async () => {
    const wrapper = await mountView()

    wrapper.vm.toggleRoadmapSort() // on
    await flushPromises()
    h.fetchProjects.mockClear()

    wrapper.vm.toggleRoadmapSort() // off
    await flushPromises()

    expect(wrapper.vm.roadmapSortActive).toBe(false)
    expect(wrapper.vm.sortBy[0]).toEqual({ key: 'created_at', order: 'desc' })
    const params = lastSortParams()
    expect(params.sort).toBe('created_at')
    expect(params.sortDir).toBe('desc')
  })
})
