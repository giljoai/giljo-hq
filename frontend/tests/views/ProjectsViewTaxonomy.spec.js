import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises, config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ProjectsView from '@/views/ProjectsView.vue'
import { useProjectStore } from '@/stores/projects'
import { useProductStore } from '@/stores/products'
import { useAgentJobsStore as useAgentStore } from '@/stores/agentJobsStore'
import { useProjectStatusesStore } from '@/stores/projectStatusesStore'

// Canonical statuses (BE-5039) so the BE-6078 status multi-select defaults to
// all-checked (full listing) and filteredProjects is populated.
const CANONICAL_STATUSES = [
  { value: 'inactive', label: 'Inactive' },
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'terminated', label: 'Terminated' },
  { value: 'deleted', label: 'Deleted' },
]

// Mock api service at module level (overrides global mock from setup.js)
vi.mock('@/services/api', () => ({
  default: {
    taxonomyTypes: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
    },
    projects: {
      checkSeries: vi.fn(() => Promise.resolve({ data: { available: true } })),
      usedSubseries: vi.fn(() => Promise.resolve({ data: { used_subseries: [] } })),
    },
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: { success: true } })),
    put: vi.fn(() => Promise.resolve({ data: { success: true } })),
    delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
  },
}))

describe('ProjectsView - Taxonomy Display (Handover 0440c)', () => {
  let router
  let projectStore
  let productStore
  let agentStore
  let savedPlugins

  const mockProduct = {
    id: 'prod-1',
    name: 'Test Product',
    is_active: true,
  }

  // Project WITH taxonomy data (series-assigned, Feature type)
  const taxonomyProject = {
    id: 'proj-tax-1',
    name: 'Taxonomy Feature Build',
    status: 'active',
    product_id: 'prod-1',
    mission: 'Build taxonomy system',
    description: 'Implement project taxonomy',
    agent_count: 2,
    created_at: '2026-02-10T00:00:00Z',
    updated_at: '2026-02-20T00:00:00Z',
    deleted_at: null,
    project_type_id: 'type-feat',
    series_number: 440,
    subseries: 'c',
    taxonomy_alias: 'FEAT-0440c',
    project_type: {
      id: 'type-feat',
      label: 'Feature',
      abbreviation: 'FEAT',
      color: '#4CAF50',
    },
  }

  // Project WITHOUT taxonomy data (legacy project)
  const legacyProject = {
    id: 'proj-legacy-1',
    name: 'Legacy Project',
    status: 'inactive',
    product_id: 'prod-1',
    mission: 'Some legacy work',
    description: 'No taxonomy assigned',
    agent_count: 1,
    created_at: '2026-01-15T00:00:00Z',
    updated_at: '2026-02-01T00:00:00Z',
    deleted_at: null,
    project_type_id: null,
    series_number: null,
    subseries: null,
    taxonomy_alias: null,
    project_type: null,
  }

  // Second taxonomy project (Bugfix type)
  const taxonomyProjectBugfix = {
    id: 'proj-tax-2',
    name: 'Fix Login Bug',
    status: 'inactive',
    product_id: 'prod-1',
    mission: 'Fix authentication bug',
    description: 'Debug login flow',
    agent_count: 1,
    created_at: '2026-02-12T00:00:00Z',
    updated_at: '2026-02-18T00:00:00Z',
    deleted_at: null,
    project_type_id: 'type-bug',
    series_number: 501,
    subseries: null,
    taxonomy_alias: 'BUG-0501',
    project_type: {
      id: 'type-bug',
      label: 'Bugfix',
      abbreviation: 'BUG',
      color: '#F44336',
    },
  }

  const mockProjectTypes = [
    {
      id: 'type-feat',
      label: 'Feature',
      abbreviation: 'FEAT',
      color: '#4CAF50',
    },
    {
      id: 'type-bug',
      label: 'Bugfix',
      abbreviation: 'BUG',
      color: '#F44336',
    },
  ]

  beforeEach(() => {
    // Replace the global pinia (from setup.js) with a fresh instance so that
    // the component's useXxxStore() calls resolve to our test stores.
    savedPlugins = [...config.global.plugins]
    const pinia = createPinia()
    setActivePinia(pinia)
    config.global.plugins = savedPlugins.map((p) => {
      if (p && typeof p === 'object' && ('_s' in p || '_a' in p)) return pinia
      return p
    })

    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/projects', component: ProjectsView },
        { path: '/projects/:id', component: { template: '<div>Detail</div>' } },
        { path: '/projects/:projectId/launch', name: 'ProjectLaunch', component: { template: '<div>Launch</div>' } },
      ],
    })

    projectStore = useProjectStore()
    productStore = useProductStore()
    agentStore = useAgentStore()

    // Mock store actions before patching state so that onMounted
    // does not reset patched state via real API calls.
    projectStore.fetchProjects = vi.fn().mockResolvedValue()
    projectStore.fetchActiveProject = vi.fn().mockResolvedValue()
    projectStore.fetchHiddenProjects = vi.fn().mockResolvedValue()
    projectStore.fetchDeletedProjects = vi.fn().mockResolvedValue()
    projectStore.createProject = vi.fn().mockResolvedValue(taxonomyProject)
    projectStore.updateProject = vi.fn().mockResolvedValue(taxonomyProject)
    projectStore.deleteProject = vi.fn().mockResolvedValue()
    projectStore.activateProject = vi.fn().mockResolvedValue()
    projectStore.pauseProject = vi.fn().mockResolvedValue()
    projectStore.completeProject = vi.fn().mockResolvedValue()
    projectStore.cancelProject = vi.fn().mockResolvedValue()
    projectStore.restoreProject = vi.fn().mockResolvedValue()

    productStore.fetchProducts = vi.fn().mockResolvedValue()
    productStore.fetchActiveProduct = vi.fn().mockResolvedValue()

    agentStore.fetchAgents = vi.fn().mockResolvedValue()

    // Set store state
    projectStore.$patch({
      projects: [taxonomyProject, legacyProject, taxonomyProjectBugfix],
      loading: false,
      error: null,
    })

    productStore.$patch({
      products: [mockProduct],
      // FE-9502c: ProjectsView now scopes by currentProduct (the viewed tab),
      // not the server's single activeProduct.
      currentProduct: mockProduct,
      activeProduct: mockProduct,
    })

    agentStore.$patch({
      agents: [],
      loading: false,
    })

    // BE-6078: seed canonical statuses so the multi-select defaults to all-checked.
    const statusesStore = useProjectStatusesStore()
    statusesStore.$patch({ statuses: CANONICAL_STATUSES })
    statusesStore.ensureLoaded = vi.fn().mockResolvedValue()
  })

  afterEach(() => {
    config.global.plugins = savedPlugins
  })

  const createWrapper = async () => {
    const wrapper = mount(ProjectsView, {
      global: {
        plugins: [router],
        stubs: { teleport: true },
        directives: { draggable: () => {} },
      },
    })
    await flushPromises()
    return wrapper
  }

  // ----------------------------------------------------------------
  // 1. Taxonomy chip data in sorted project list
  //    The v-data-table stub does not render scoped slots, so we verify
  //    the data that feeds the template rather than rendered DOM text.
  //    The template renders a v-chip when item.taxonomy_alias && item.series_number.
  // ----------------------------------------------------------------
  // BE-6076: the table renders the server PAGE (`store.projects`); these assert
  // the page rows still carry the taxonomy fields the chip template reads.
  describe('Taxonomy Chip Rendering', () => {
    it('provides taxonomy_alias and series_number for chip rendering (Feature)', async () => {
      const wrapper = await createWrapper()
      const featProject = wrapper.vm.projects.find((p) => p.id === 'proj-tax-1')

      expect(featProject).toBeTruthy()
      expect(featProject.taxonomy_alias).toBe('FEAT-0440c')
      expect(featProject.series_number).toBe(440)
      expect(featProject.project_type?.color).toBe('#4CAF50')
    })

    it('provides taxonomy_alias and series_number for chip rendering (Bugfix)', async () => {
      const wrapper = await createWrapper()
      const bugProject = wrapper.vm.projects.find((p) => p.id === 'proj-tax-2')

      expect(bugProject).toBeTruthy()
      expect(bugProject.taxonomy_alias).toBe('BUG-0501')
      expect(bugProject.series_number).toBe(501)
      expect(bugProject.project_type?.color).toBe('#F44336')
    })

    it('legacy project has no taxonomy_alias or series_number (no chip rendered)', async () => {
      projectStore.$patch({ projects: [legacyProject] })

      const wrapper = await createWrapper()
      const legacy = wrapper.vm.projects.find((p) => p.id === 'proj-legacy-1')

      expect(legacy).toBeTruthy()
      expect(legacy.name).toBe('Legacy Project')
      // These being falsy means the v-if="item.taxonomy_alias && item.series_number" is false
      expect(legacy.taxonomy_alias).toBeFalsy()
      expect(legacy.series_number).toBeFalsy()
    })

    it('mixed list contains both taxonomy and non-taxonomy projects', async () => {
      const wrapper = await createWrapper()
      const sorted = wrapper.vm.projects

      expect(sorted.length).toBe(3)

      const withTaxonomy = sorted.filter((p) => p.taxonomy_alias && p.series_number)
      const withoutTaxonomy = sorted.filter((p) => !p.taxonomy_alias || !p.series_number)

      expect(withTaxonomy.length).toBe(2)
      expect(withoutTaxonomy.length).toBe(1)
      expect(withoutTaxonomy[0].name).toBe('Legacy Project')
    })
  })

  // ----------------------------------------------------------------
  // 2. Type filter chip rendering
  // ----------------------------------------------------------------
  describe('Filter Bar Rendering', () => {
    it('renders the filter bar', async () => {
      const wrapper = await createWrapper()
      const filterBar = wrapper.find('.filter-bar')
      expect(filterBar.exists()).toBe(true)
    })

    it('renders search field in filter bar', async () => {
      const wrapper = await createWrapper()

      const searchField = wrapper.find('.filter-search')
      expect(searchField.exists()).toBe(true)
    })

    // BE-6078: the Type dropdown was removed (search already matches
    // taxonomy_alias, e.g. typing "FEAT-"), so the composable no longer exposes
    // a Type filter surface.
    it('no longer exposes the removed Type filter state', async () => {
      const wrapper = await createWrapper()
      expect(wrapper.vm.filterType).toBeUndefined()
      expect(wrapper.vm.typeSelectOptions).toBeUndefined()
    })
  })

  // ----------------------------------------------------------------
  // 3. BE-6076: search is SERVER-side. Typing an alias prefix (e.g. "FEAT-")
  //    forwards the raw query to the backend (ILIKE across name/id/alias —
  //    case-insensitivity is a SQL concern, covered by the backend test).
  // ----------------------------------------------------------------
  describe('search - forwarded to the server', () => {
    it('forwards a taxonomy_alias query to the server (debounced)', async () => {
      vi.useFakeTimers()
      const wrapper = await createWrapper()
      wrapper.vm.searchQuery = 'FEAT-0440'
      await wrapper.vm.$nextTick()
      vi.advanceTimersByTime(350)
      await flushPromises()
      vi.useRealTimers()

      const calls = projectStore.fetchProjects.mock.calls
      const params = calls[calls.length - 1][0]
      expect(params.search).toBe('FEAT-0440')
    })
  })

  // ----------------------------------------------------------------
  // 4. BE-6076: sorting is server-side; the table renders the server page rows
  //    (here the patched store set). These assert the page carries the expected
  //    rows the chip/sort columns read.
  // ----------------------------------------------------------------
  describe('Server page content', () => {
    it('the page includes both inactive taxonomy and legacy projects', async () => {
      const wrapper = await createWrapper()
      const projects = wrapper.vm.projects
      const inactiveProjects = projects.filter((p) => p.status === 'inactive')
      expect(inactiveProjects.length).toBe(2)

      const bugProject = inactiveProjects.find((p) => p.id === 'proj-tax-2')
      const legacyProj = inactiveProjects.find((p) => p.id === 'proj-legacy-1')
      expect(bugProject).toBeTruthy()
      expect(legacyProj).toBeTruthy()
    })

    it('the page includes active projects', async () => {
      const wrapper = await createWrapper()
      const projects = wrapper.vm.projects
      expect(projects.length).toBeGreaterThan(0)
      const activeProject = projects.find((p) => p.id === 'proj-tax-1')
      expect(activeProject).toBeTruthy()
      expect(activeProject.status).toBe('active')
    })

    it('the page carries multiple Feature projects with correct series_numbers', async () => {
      const secondFeature = {
        ...taxonomyProject,
        id: 'proj-tax-3',
        name: 'Another Feature',
        status: 'inactive',
        series_number: 100,
        taxonomy_alias: 'FEAT-0100',
      }
      const inactiveTaxonomy = { ...taxonomyProject, status: 'inactive' }

      projectStore.$patch({
        projects: [inactiveTaxonomy, secondFeature, legacyProject, taxonomyProjectBugfix],
      })

      const wrapper = await createWrapper()
      await wrapper.vm.$nextTick()

      const projects = wrapper.vm.projects
      const featProjects = projects.filter((p) => p.project_type?.abbreviation === 'FEAT')

      expect(featProjects.length).toBe(2)
      const seriesNumbers = featProjects.map((p) => p.series_number).sort((a, b) => a - b)
      expect(seriesNumbers[0]).toBe(100)
      expect(seriesNumbers[1]).toBe(440)
    })
  })

  // 0950k: Sections 5-9 removed — taxonomy form state (projectData, seriesNumberInput,
  // seriesCheckResult, typeDropdownItems, subseriesItems, handleTypeChange, onSubseriesChange,
  // resetForm, cleanup) moved to ProjectCreateEditDialog via useProjectTaxonomy composable.
  // Covered by useProjectTaxonomy.spec.js (13 tests).

})
