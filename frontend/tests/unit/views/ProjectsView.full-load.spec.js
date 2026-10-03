/**
 * BE-6078 — ProjectsView full-load behavior (replaces the IMP-1002 status-filter
 * server re-fetch suite, whose watch was removed when Status became a client-side
 * multi-select).
 *
 * The Projects page now loads the FULL set on mount (all lifecycle statuses,
 * hidden excluded server-side) plus the hidden set (for "Show hidden (N)"); the
 * multi-select Status filter then runs client-side. There is no longer a
 * filterStatus → server re-fetch.
 *
 * Edition Scope: CE
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'

// ── hoisted mock refs ──────────────────────────────────────────────────────────

const { mockFetchProjects, mockFetchHiddenProjects, mockFetchDeletedProjects, mockFetchProject } = vi.hoisted(() => ({
  mockFetchProjects: vi.fn().mockResolvedValue(),
  mockFetchHiddenProjects: vi.fn().mockResolvedValue(),
  mockFetchDeletedProjects: vi.fn().mockResolvedValue(),
  mockFetchProject: vi.fn().mockResolvedValue(null),
}))

// ── mocks ──────────────────────────────────────────────────────────────────────

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    projects: [],
    deletedProjects: [],
    hiddenProjects: [],
    // BE-6076: server-mode page state + active-project flag.
    projectsTotal: 0,
    loading: false,
    error: null,
    fetchProjects: mockFetchProjects,
    fetchActiveProject: vi.fn().mockResolvedValue(),
    fetchHiddenProjects: mockFetchHiddenProjects,
    fetchDeletedProjects: mockFetchDeletedProjects,
    fetchProject: mockFetchProject,
    createProject: vi.fn().mockResolvedValue(),
    updateProject: vi.fn().mockResolvedValue(),
    deleteProject: vi.fn().mockResolvedValue(),
    restoreProject: vi.fn().mockResolvedValue(),
    purgeDeletedProject: vi.fn().mockResolvedValue(),
    purgeAllDeletedProjects: vi.fn().mockResolvedValue(),
    activateProject: vi.fn().mockResolvedValue(),
    deactivateProject: vi.fn().mockResolvedValue(),
    completeProject: vi.fn().mockResolvedValue(),
    cancelProject: vi.fn().mockResolvedValue(),
    projectById: vi.fn().mockReturnValue(null),
  }),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    activeProduct: { id: 'prod-1', name: 'Test Product' },
    products: [{ id: 'prod-1', name: 'Test Product' }],
    productMetrics: {},
    productCount: 1,
    activeProductId: 'prod-1',
    activeProductAlias: null,
    fetchProducts: vi.fn().mockResolvedValue(),
    fetchActiveProduct: vi.fn().mockResolvedValue(),
  }),
}))

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({
    clearForProject: vi.fn(),
  }),
}))

vi.mock('@/stores/agentJobsStore', async (importOriginal) => {
  const original = await importOriginal()
  return {
    ...original,
    useAgentJobsStore: () => ({
      fetchAgents: vi.fn().mockResolvedValue(),
      agents: [],
      jobs: [],
      sortedJobs: [],
      jobCount: 0,
      setJobs: vi.fn(),
      upsertJob: vi.fn(),
      removeJob: vi.fn(),
      getJob: vi.fn(),
      resolveJobId: vi.fn(),
      handleCreated: vi.fn(),
      handleUpdated: vi.fn(),
      handleStatusChanged: vi.fn(),
      handleProgressUpdate: vi.fn(),
      flushPendingUpdates: vi.fn(),
      $reset: vi.fn(),
    }),
  }
})

vi.mock('@/stores/projectTabs', () => ({
  useProjectTabsStore: () => ({
    currentProject: null,
    isLaunched: false,
  }),
}))

// projectStatusesStore: provide real getMeta that returns is_lifecycle_finished
// so the watcher logic can classify statuses correctly.
vi.mock('@/stores/projectStatusesStore', () => {
  const FINISHED = new Set(['completed', 'cancelled', 'terminated', 'deleted'])
  const getMeta = (value) => {
    if (!value) return undefined
    return { is_lifecycle_finished: FINISHED.has(value) }
  }
  return {
    useProjectStatusesStore: () => ({
      statuses: ref([
        { value: 'inactive', label: 'Inactive', is_lifecycle_finished: false },
        { value: 'active', label: 'Active', is_lifecycle_finished: false },
        { value: 'completed', label: 'Completed', is_lifecycle_finished: true },
        { value: 'cancelled', label: 'Cancelled', is_lifecycle_finished: true },
        { value: 'terminated', label: 'Terminated', is_lifecycle_finished: true },
        { value: 'deleted', label: 'Deleted', is_lifecycle_finished: true },
      ]),
      getMeta,
      ensureLoaded: vi.fn().mockResolvedValue(),
      isValid: vi.fn().mockReturnValue(true),
    }),
  }
})

vi.mock('@/components/StatusBadge.vue', () => ({
  default: { template: '<div />' },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

// ── api mock ───────────────────────────────────────────────────────────────────

vi.mock('@/services/api', () => ({
  default: {
    taxonomyTypes: { list: vi.fn().mockResolvedValue({ data: [] }) },
    projects: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      get: vi.fn().mockResolvedValue({ data: null }),
    },
  },
  api: {
    taxonomyTypes: { list: vi.fn().mockResolvedValue({ data: [] }) },
    projects: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      get: vi.fn().mockResolvedValue({ data: null }),
    },
  },
}))

// ── mount helper ───────────────────────────────────────────────────────────────

import ProjectsView from '@/views/ProjectsView.vue'

const globalStubs = {
  'v-btn': { template: '<button class="v-btn" v-bind="$attrs"><slot /></button>' },
  'v-icon': { template: '<span class="v-icon"><slot /></span>' },
  'v-text-field': { template: '<input v-bind="$attrs" />' },
  'v-menu': { template: '<div><slot /></div>' },
  'v-data-table': { template: '<div><slot /></div>' },
  'v-form': { template: '<form><slot /></form>' },
  'v-sheet': { template: '<div><slot /></div>' },
  'v-select': { template: '<select v-bind="$attrs"><slot /></select>' },
}

function mountView() {
  return mount(ProjectsView, { global: { stubs: globalStubs } })
}

// ── suite ──────────────────────────────────────────────────────────────────────

describe('ProjectsView — BE-6076 server-mode load on mount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('onMounted loads a server PAGE with the full default status set (finished projects listable)', async () => {
    mountView()
    await nextTick()
    await nextTick()

    expect(mockFetchProjects).toHaveBeenCalled()
    const params = mockFetchProjects.mock.calls[0][0]
    // Server-mode page query: pagination + the all-checked default multi-select
    // (so completed/cancelled/terminated ARE listable, BE-6078 intent preserved).
    expect(params).toHaveProperty('limit')
    expect(params).toHaveProperty('offset')
    expect(params.statuses).toEqual(
      expect.arrayContaining(['active', 'inactive', 'completed', 'cancelled', 'terminated']),
    )
  })

  it('onMounted fetches the hidden set (for the "Show hidden (N)" count)', async () => {
    mountView()
    await nextTick()
    await nextTick()

    expect(mockFetchHiddenProjects).toHaveBeenCalled()
  })

  it('never issues a bare/active-only fetch on the Projects page (would drop finished rows)', async () => {
    mountView()
    await nextTick()
    await nextTick()

    // Every fetchProjects call from this view carries server-mode params with the
    // status multi-select (or a search) — never a bare active-only default.
    for (const args of mockFetchProjects.mock.calls) {
      const p = args[0] || {}
      expect('statuses' in p || 'search' in p).toBe(true)
    }
  })

  it('exposes the multi-select selectedStatuses (no single filterStatus)', async () => {
    const wrapper = mountView()
    await nextTick()

    expect(Array.isArray(wrapper.vm.selectedStatuses)).toBe(true)
    expect(wrapper.vm.filterStatus).toBeUndefined()
  })
})
