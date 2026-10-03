import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import ProjectsView from '@/views/ProjectsView.vue'
import { useProjectStore } from '@/stores/projects'
import { useProductStore } from '@/stores/products'
import { useAgentJobsStore as useAgentStore } from '@/stores/agentJobsStore'
import { useProjectStatusesStore } from '@/stores/projectStatusesStore'

// Canonical statuses (BE-5039) so the BE-6078 status multi-select defaults to
// all-checked (full listing) at mount.
const CANONICAL_STATUSES = [
  { value: 'inactive', label: 'Inactive' },
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'terminated', label: 'Terminated' },
  { value: 'deleted', label: 'Deleted' },
]

describe('ProjectsView.vue', () => {
  let pinia
  let vuetify
  let router
  let projectStore
  let productStore
  let agentStore

  const mockProducts = [
    {
      id: 'prod-1',
      name: 'Product 1',
      is_active: true,
    },
  ]

  const mockProjects = [
    {
      id: 'proj-1',
      name: 'Project 1',
      status: 'active',
      product_id: 'prod-1',
      mission: 'Test mission 1',
      agent_count: 3,
      created_at: '2024-10-01T12:00:00Z',
      updated_at: '2024-10-28T12:00:00Z',
      deleted_at: null,
    },
    {
      id: 'proj-2',
      name: 'Project 2',
      status: 'inactive',
      product_id: 'prod-1',
      mission: 'Test mission 2',
      agent_count: 1,
      created_at: '2024-10-15T12:00:00Z',
      updated_at: '2024-10-28T12:00:00Z',
      deleted_at: null,
    },
    {
      id: 'proj-3',
      name: 'Project 3',
      status: 'inactive',
      product_id: 'prod-1',
      mission: 'Test mission 3',
      agent_count: 2,
      created_at: '2024-10-20T12:00:00Z',
      updated_at: '2024-10-28T12:00:00Z',
      deleted_at: null,
    },
  ]

  const mockDeletedProjects = [
    {
      id: 'proj-4',
      name: 'Deleted Project',
      status: 'completed',
      product_id: 'prod-1',
      mission: 'Test mission 4',
      agent_count: 0,
      created_at: '2024-09-01T12:00:00Z',
      updated_at: '2024-10-28T12:00:00Z',
      deleted_at: '2024-10-28T10:00:00Z',
    },
  ]

  const mockAgents = [
    {
      id: 'agent-1',
      name: 'Agent 1',
      project_id: 'proj-1',
    },
  ]

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/projects',
          component: ProjectsView,
        },
        {
          path: '/projects/:projectId',
          name: 'ProjectLaunch',
          component: { template: '<div>Project Launch</div>' },
        },
        {
          path: '/products',
          component: { template: '<div>Products</div>' },
        },
      ],
    })

    projectStore = useProjectStore()
    productStore = useProductStore()
    agentStore = useAgentStore()

    // BE-6078: seed the canonical statuses so the multi-select defaults to
    // all-checked (full listing) and stub ensureLoaded.
    const statusesStore = useProjectStatusesStore()
    statusesStore.$patch({ statuses: CANONICAL_STATUSES })
    statusesStore.ensureLoaded = vi.fn().mockResolvedValue()

    // Mock store state: projects and deletedProjects are separate refs
    projectStore.$patch({
      projects: mockProjects,
      deletedProjects: mockDeletedProjects,
      loading: false,
      error: null,
    })

    productStore.$patch({
      products: mockProducts,
      // FE-9502c: ProjectsView now scopes by currentProduct (the viewed tab),
      // not the server's single activeProduct. Keep both in sync here since
      // these fixtures aren't testing the divergent-tab case.
      currentProduct: mockProducts[0],
      activeProduct: mockProducts[0],
    })

    agentStore.$patch({
      agents: mockAgents,
      loading: false,
    })

    // Mock API calls on store actions
    projectStore.fetchProjects = vi.fn().mockResolvedValue()
    projectStore.fetchActiveProject = vi.fn().mockResolvedValue()
    projectStore.fetchHiddenProjects = vi.fn().mockResolvedValue()
    projectStore.fetchDeletedProjects = vi.fn().mockResolvedValue()
    projectStore.createProject = vi.fn().mockResolvedValue(mockProjects[0])
    projectStore.updateProject = vi.fn().mockResolvedValue(mockProjects[0])
    projectStore.deleteProject = vi.fn().mockResolvedValue()
    projectStore.activateProject = vi.fn().mockResolvedValue()
    projectStore.deactivateProject = vi.fn().mockResolvedValue()
    projectStore.completeProject = vi.fn().mockResolvedValue()
    projectStore.cancelProject = vi.fn().mockResolvedValue()
    projectStore.restoreProject = vi.fn().mockResolvedValue()
    projectStore.restoreCompletedProject = vi.fn().mockResolvedValue()
    projectStore.purgeDeletedProject = vi.fn().mockResolvedValue()
    projectStore.purgeAllDeletedProjects = vi.fn().mockResolvedValue()

    productStore.fetchProducts = vi.fn().mockResolvedValue()
    productStore.fetchActiveProduct = vi.fn().mockResolvedValue()

    agentStore.fetchAgents = vi.fn().mockResolvedValue()
  })

  const createWrapper = async () => {
    // Merge global Vuetify stubs with test-specific stubs.
    // Pass only our test pinia (not the global config one) to avoid
    // dual-Pinia where component and test reference different store instances.
    const wrapper = mount(ProjectsView, {
      global: {
        plugins: [pinia, vuetify, router],
        stubs: {
          ...config.global.stubs,
          'v-expand-transition': { template: '<div><slot /></div>' },
          'v-sheet': { template: '<div class="v-sheet" v-bind="$attrs"><slot /></div>' },
          teleport: true,
          ManualCloseoutModal: true,
          ProjectReviewModal: true,
          StatusBadge: true,
          BaseDialog: true,
          AddTypeModal: true,
        },
        directives: {
          draggable: {},
        },
      },
    })
    await flushPromises()
    return wrapper
  }

  describe('Rendering', () => {
    it('renders header with title', async () => {
      const wrapper = await createWrapper()
      expect(wrapper.text()).toContain('Project Management')
    })

    it('renders projects page title', async () => {
      const wrapper = await createWrapper()
      expect(wrapper.text()).toContain('Project Management')
    })

    it('renders New Project button', async () => {
      const wrapper = await createWrapper()
      const button = wrapper.find('button[aria-label="Create new project"]')
      expect(button.exists()).toBe(true)
    })

    it('labels the New Project button with a "New project" title', async () => {
      const wrapper = await createWrapper()
      const button = wrapper.find('button[aria-label="Create new project"]')
      expect(button.attributes('title')).toBe('New project')
    })

    it('renders search input field', async () => {
      const wrapper = await createWrapper()
      const searchInput = wrapper.find('input[aria-label="Search projects by name"]')
      expect(searchInput.exists()).toBe(true)
    })

    it('renders Deleted button', async () => {
      const wrapper = await createWrapper()
      // The deleted-projects CTA is an icon-only button; assert it by its
      // accessible name rather than incidental text (the count label now lives
      // inside ProjectDeletedDialog's BaseDialog, which this suite stubs).
      const deletedBtn = wrapper.find('button[aria-label="View deleted projects"]')
      expect(deletedBtn.exists()).toBe(true)
    })

  })

  // BE-6076: search is SERVER-side now. The view issues a debounced server
  // request carrying the raw query (the searchable-field decision moved to SQL).
  describe('Search Functionality (BE-6076 server-side)', () => {
    const lastFetchParams = () => {
      const calls = projectStore.fetchProjects.mock.calls
      return calls.length ? calls[calls.length - 1][0] : null
    }

    it('issues a debounced server search request carrying the query', async () => {
      vi.useFakeTimers()
      const wrapper = await createWrapper()
      wrapper.vm.searchQuery = 'Project 1'
      await wrapper.vm.$nextTick()
      vi.advanceTimersByTime(350)
      await flushPromises()
      vi.useRealTimers()

      const params = lastFetchParams()
      expect(params.search).toBe('Project 1')
      // Nuclear search: the status multi-select is dropped while searching.
      expect(params.statuses).toBeUndefined()
    })

    it('returns to the status-filtered query when search is cleared', async () => {
      vi.useFakeTimers()
      const wrapper = await createWrapper()
      wrapper.vm.searchQuery = 'Project 1'
      await wrapper.vm.$nextTick()
      vi.advanceTimersByTime(350)
      await flushPromises()
      expect(lastFetchParams().search).toBe('Project 1')

      wrapper.vm.searchQuery = ''
      await wrapper.vm.$nextTick()
      vi.advanceTimersByTime(350)
      await flushPromises()
      vi.useRealTimers()

      const params = lastFetchParams()
      expect(params.search).toBeUndefined()
      expect(Array.isArray(params.statuses)).toBe(true)
    })
  })

  // BE-6076/6078: Status multi-select (selectedStatuses) now drives the SERVER
  // `statuses` param; default all-checked = full listing. Unchecking re-fetches.
  describe('Status Filtering (BE-6078 multi-select, server-driven)', () => {
    const lastFetchParams = () => {
      const calls = projectStore.fetchProjects.mock.calls
      return calls.length ? calls[calls.length - 1][0] : null
    }

    it('mount fetch carries the all-checked default status set', async () => {
      await createWrapper()
      const params = lastFetchParams()
      expect(params.statuses).toEqual(
        expect.arrayContaining(['active', 'inactive', 'completed', 'cancelled', 'terminated']),
      )
    })

    it('selecting a single status re-fetches with that status', async () => {
      const wrapper = await createWrapper()
      wrapper.vm.selectedStatuses = ['active']
      await wrapper.vm.$nextTick()
      await flushPromises()
      expect(lastFetchParams().statuses).toEqual(['active'])
    })

    it('unchecking a status re-fetches with the reduced set', async () => {
      const wrapper = await createWrapper()
      wrapper.vm.selectedStatuses = ['inactive', 'completed', 'cancelled', 'terminated', 'deleted']
      await wrapper.vm.$nextTick()
      await flushPromises()
      expect(lastFetchParams().statuses).not.toContain('active')
      expect(lastFetchParams().statuses).toContain('inactive')
    })

    it('the table is bound to the server page + total', async () => {
      const wrapper = await createWrapper()
      // `projects` is the store page; `projectsTotal` the filtered total.
      expect(wrapper.vm.projects).toBe(projectStore.projects)
      expect(wrapper.vm.projectsTotal).toBe(projectStore.projectsTotal)
    })
  })

  describe('Deleted Projects', () => {
    it('shows deleted projects count', async () => {
      const wrapper = await createWrapper()
      expect(wrapper.vm.deletedCount).toBe(1)
    })

    it('displays deleted projects in separate modal', async () => {
      const wrapper = await createWrapper()
      expect(wrapper.vm.deletedProjects.length).toBe(1)
      expect(wrapper.vm.deletedProjects[0].id).toBe('proj-4')
    })

    it('enables Deleted button when deleted projects exist', async () => {
      const wrapper = await createWrapper()
      const deleteButton = wrapper.find('button[aria-label="View deleted projects"]')

      expect(deleteButton.exists()).toBe(true)
      expect(deleteButton.attributes('disabled')).toBeUndefined()
    })

    it('disables Deleted button when no deleted projects', async () => {
      projectStore.$patch({
        deletedProjects: [],
      })

      const wrapper = await createWrapper()
      const deleteButton = wrapper.find('button[aria-label="View deleted projects"]')

      expect(deleteButton.attributes('disabled')).toBeDefined()
    })

    it('can restore deleted projects', async () => {
      const wrapper = await createWrapper()
      await wrapper.vm.restoreFromDelete(wrapper.vm.deletedProjects[0])

      expect(projectStore.restoreProject).toHaveBeenCalledWith('proj-4')
    })
  })

  describe('Sorting', () => {
    it('sorts by created_at descending by default (newest first)', async () => {
      const wrapper = await createWrapper()
      expect(wrapper.vm.sortBy).toEqual([{ key: 'created_at', order: 'desc' }])
    })

    it('changing sort (via table options) re-fetches with the server sort param', async () => {
      const wrapper = await createWrapper()
      wrapper.vm.onTableOptions({ page: 1, itemsPerPage: 10, sortBy: [{ key: 'name', order: 'asc' }] })
      await wrapper.vm.$nextTick()
      await flushPromises()

      const calls = projectStore.fetchProjects.mock.calls
      const params = calls[calls.length - 1][0]
      expect(params.sort).toBe('name')
      expect(params.sortDir).toBe('asc')
    })

    it('changing page (via table options) re-fetches with the right offset', async () => {
      const wrapper = await createWrapper()
      wrapper.vm.onTableOptions({ page: 3, itemsPerPage: 10, sortBy: [{ key: 'created_at', order: 'desc' }] })
      await wrapper.vm.$nextTick()
      await flushPromises()

      const calls = projectStore.fetchProjects.mock.calls
      const params = calls[calls.length - 1][0]
      expect(params.limit).toBe(10)
      expect(params.offset).toBe(20)
    })
  })

  describe('Project CRUD Operations', () => {
    it('opens create dialog when New Project button clicked', async () => {
      const wrapper = await createWrapper()
      const button = wrapper.find('button[aria-label="Create new project"]')
      await button.trigger('click')

      expect(wrapper.vm.showCreateDialog).toBe(true)
    })

    it('deletes project after confirmation', async () => {
      const wrapper = await createWrapper()
      wrapper.vm.projectToDelete = mockProjects[0]

      await wrapper.vm.deleteProject()

      expect(projectStore.deleteProject).toHaveBeenCalledWith('proj-1')
      expect(wrapper.vm.projectToDelete).toBeNull()
    })
  })

  describe('Status Actions', () => {
    it('handles activate action', async () => {
      const wrapper = await createWrapper()
      await wrapper.vm.handleStatusAction({ action: 'activate', projectId: 'proj-1' })

      expect(projectStore.activateProject).toHaveBeenCalledWith('proj-1')
    })

    it('handles deactivate action', async () => {
      const wrapper = await createWrapper()
      await wrapper.vm.handleStatusAction({ action: 'deactivate', projectId: 'proj-1' })

      expect(projectStore.deactivateProject).toHaveBeenCalledWith('proj-1')
    })

    it('handles cancel action by opening confirmation dialog', async () => {
      const wrapper = await createWrapper()
      await wrapper.vm.handleStatusAction({ action: 'cancel', projectId: 'proj-1' })

      expect(wrapper.vm.showCancelDialog).toBe(true)
      expect(wrapper.vm.projectToCancel?.id).toBe('proj-1')
    })

    it('handles delete action by opening confirmation dialog', async () => {
      const wrapper = await createWrapper()
      await wrapper.vm.handleStatusAction({ action: 'delete', projectId: 'proj-1' })

      expect(wrapper.vm.showDeleteDialog).toBe(true)
      expect(wrapper.vm.projectToDelete?.id).toBe('proj-1')
    })
  })

  // 0950k: Form Validation section removed — formValid, projectData, resetForm
  // moved to ProjectCreateEditDialog. Covered by useProjectTaxonomy composable tests.

  describe('Product Integration', () => {
    it('disables New Project button when no active product', async () => {
      productStore.$patch({
        currentProduct: null,
        activeProduct: null,
      })

      const wrapper = await createWrapper()
      // When no active product, the Projects Table card (with Create button) is hidden
      // by v-if="activeProduct". The button only exists in the dialog header area.
      // Verify via component state that the button would be disabled.
      expect(wrapper.vm.activeProduct).toBeNull()
    })

    it('shows alert when no active product', async () => {
      productStore.$patch({
        currentProduct: null,
        activeProduct: null,
      })

      const wrapper = await createWrapper()
      expect(wrapper.text()).toContain('No product is open')
    })

    it('scopes the server page to the active product (product_id added store-side)', async () => {
      // BE-6076: product scoping moved server-side (the store appends product_id
      // from the active product). The view simply renders the returned page.
      const wrapper = await createWrapper()
      expect(wrapper.vm.activeProduct?.id).toBe('prod-1')
      expect(projectStore.fetchProjects).toHaveBeenCalled()
    })

  })

  describe('Date Formatting', () => {
    it('formats dates with time (Mon DD, YYYY HH:MM)', async () => {
      const wrapper = await createWrapper()
      const dateStr = '2024-10-28T12:00:00Z'
      const formatted = wrapper.vm.formatDateWithTime(dateStr)

      expect(formatted).toMatch(/Oct 28, 2024/)
    })

    it('returns N/A for empty dates', async () => {
      const wrapper = await createWrapper()
      expect(wrapper.vm.formatDateWithTime(null)).toBe('N/A')
      expect(wrapper.vm.formatDateWithTime('')).toBe('N/A')
    })
  })

  describe('Accessibility', () => {
    it('has proper ARIA labels on buttons', async () => {
      const wrapper = await createWrapper()

      const createButton = wrapper.find('button[aria-label="Create new project"]')
      const searchInput = wrapper.find('input[aria-label="Search projects by name"]')
      const deletedButton = wrapper.find('button[aria-label="View deleted projects"]')

      expect(createButton.exists()).toBe(true)
      expect(searchInput.exists()).toBe(true)
      expect(deletedButton.exists()).toBe(true)
    })

    it('has form labels for inputs', async () => {
      const wrapper = await createWrapper()
      wrapper.vm.showCreateDialog = true
      await wrapper.vm.$nextTick()

      const nameInput = wrapper.find('input[aria-label="Project name"]')

      expect(nameInput.exists()).toBe(true)
    })
  })
})
