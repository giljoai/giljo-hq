import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

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
  await flushPromises()
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
    const params = lastSortParams()
    expect(params.sort).toBe('roadmap')
    expect(params.sortDir).toBe('asc')
  })

  it('toggle OFF -> reverts to the default newest-first server sort', async () => {
    const wrapper = await mountView()

    wrapper.vm.toggleRoadmapSort()
    await flushPromises()
    h.fetchProjects.mockClear()

    wrapper.vm.toggleRoadmapSort()
    await flushPromises()

    expect(wrapper.vm.roadmapSortActive).toBe(false)
    expect(wrapper.vm.sortBy[0]).toEqual({ key: 'created_at', order: 'desc' })
    const params = lastSortParams()
    expect(params.sort).toBe('created_at')
    expect(params.sortDir).toBe('desc')
  })
})
