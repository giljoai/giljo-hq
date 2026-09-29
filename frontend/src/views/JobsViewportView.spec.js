import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({ getActive: vi.fn(), listAgentJobs: vi.fn() }))

vi.mock('@/services/api', () => ({
  api: {
    projects: {
      getActive: (...a) => h.getActive(...a),
    },
    agentJobs: {
      list: (...a) => h.listAgentJobs(...a),
    },
  },
}))

const handleMessagesMock = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useJobActions', () => ({
  useJobActions: () => ({ handleMessages: handleMessagesMock }),
}))

import JobsViewportView from './JobsViewportView.vue'
import { useProductStore } from '@/stores/products'
import { useJobsScopeStore } from '@/stores/jobsScope'

let pinia
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})

function envelope(jobs) {
  return { data: { jobs, total: jobs.length, limit: 50, offset: 0 } }
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  window.localStorage.getItem.mockImplementation((k) => (k === 'jobs.density.v2' ? 'detailed' : null))
  h.listAgentJobs.mockResolvedValue(envelope([]))
})

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

function mountView() {
  return mount(JobsViewportView, {
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
}

const NEEDS_INPUT_PROJECT = {
  id: 'proj-1',
  taxonomy_alias: 'BE-6174',
  name: 'Flip the headless launch fence',
  status: 'active',
  implementation_launched_at: '2026-08-30T22:14:00Z',
}
const NEEDS_INPUT_AGENTS = [
  { agent_id: 'a-or', job_id: 'j-or', agent_display_name: 'orchestrator', status: 'waiting' },
  { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'blocked' },
]

describe('JobsViewportView', () => {
  it('shows the new empty state (D8 vocabulary: no "Active"/"Activate")', async () => {
    h.getActive.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="jobs-board-empty"]').text()).toContain('Nothing in flight')
    expect(wrapper.find('[data-testid="jobs-board-empty"]').text()).not.toContain('for this product')
    expect(wrapper.find('[data-testid="jobs-board-empty"]').text()).toContain('Stage a project to see its agents here.')
    expect(wrapper.text()).not.toMatch(/\bActive\b/)
    expect(wrapper.text()).not.toMatch(/\bActivate\b/)
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(0)
  })

  it('renders one JobsBoardCard per in-flight project, using the real paginated agent-jobs envelope', async () => {
    h.getActive.mockResolvedValue({
      data: [
        NEEDS_INPUT_PROJECT,
        { id: 'proj-2', taxonomy_alias: 'FE-6175', name: 'Lifecycle banners', status: 'active', implementation_launched_at: null },
      ],
    })
    h.listAgentJobs.mockImplementation((projectId) =>
      Promise.resolve(envelope(projectId === 'proj-1' ? NEEDS_INPUT_AGENTS : [])),
    )

    const wrapper = mountView()
    await flushPromises()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Flip the headless launch fence')
    await wrapper.find('[data-testid="jobs-side-staging"]').trigger('click')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Lifecycle banners')
  })

  it('a third project appearing on a later fetch (live update) is reflected without a manual reload', async () => {
    h.getActive.mockResolvedValue({
      data: [
        { id: 'proj-1', name: 'Alpha', status: 'active', implementation_launched_at: null },
        { id: 'proj-2', name: 'Beta', status: 'active', implementation_launched_at: null },
      ],
    })

    const wrapper = mountView()
    await flushPromises()
    await flushPromises()
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(2)

    h.getActive.mockResolvedValue({
      data: [
        { id: 'proj-1', name: 'Alpha', status: 'active', implementation_launched_at: null },
        { id: 'proj-2', name: 'Beta', status: 'active', implementation_launched_at: null },
        { id: 'proj-3', name: 'Gamma', status: 'active', implementation_launched_at: null },
      ],
    })
    const { useProjectStore } = await import('@/stores/projects')
    await useProjectStore(pinia).fetchActiveProject()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(3)
    expect(wrapper.text()).toContain('Gamma')
  })

  it('the filter toolbar narrows the grid without changing the underlying project set', async () => {
    h.getActive.mockResolvedValue({
      data: [
        NEEDS_INPUT_PROJECT,
        { id: 'proj-2', taxonomy_alias: 'FE-6175', name: 'Lifecycle banners', status: 'active', implementation_launched_at: '2026-08-30T23:02:00Z' },
      ],
    })
    h.listAgentJobs.mockImplementation((projectId) =>
      Promise.resolve(envelope(projectId === 'proj-1' ? NEEDS_INPUT_AGENTS : [{ agent_display_name: 'orchestrator', status: 'working' }])),
    )

    const wrapper = mountView()
    await flushPromises()
    await flushPromises()
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(2)

    await wrapper.find('[data-testid="jobs-filter-needs-input"]').trigger('click')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Flip the headless launch fence')

    await wrapper.find('[data-testid="jobs-filter-all"]').trigger('click')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(2)
  })

  it('the filter toolbar covers Activated and Planning, each with a live count', async () => {
    h.getActive.mockResolvedValue({
      data: [
        { id: 'proj-1', taxonomy_alias: 'BE-1', name: 'Never staged', status: 'active', staging_status: null, implementation_launched_at: null },
        { id: 'proj-2', taxonomy_alias: 'BE-2', name: 'Mid staging', status: 'active', staging_status: 'staging', implementation_launched_at: null },
      ],
    })

    const wrapper = mountView()
    await flushPromises()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('Activated')
    expect(wrapper.text()).toContain('Planning')

    const activatedFilter = wrapper.find('[data-testid="jobs-filter-activated"]')
    expect(activatedFilter.exists()).toBe(true)
    expect(activatedFilter.text()).toContain('1')

    const planningFilter = wrapper.find('[data-testid="jobs-filter-planning"]')
    expect(planningFilter.exists()).toBe(true)
    expect(planningFilter.text()).toContain('1')

    await activatedFilter.trigger('click')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Never staged')

    await planningFilter.trigger('click')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Mid staging')
  })

  it('opening a card\'s "Jobs detail" opens the ONE shared detail modal with that project\'s agents', async () => {
    h.getActive.mockResolvedValue({ data: [NEEDS_INPUT_PROJECT] })
    h.listAgentJobs.mockResolvedValue(envelope(NEEDS_INPUT_AGENTS))

    const wrapper = mountView()
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="jb-btn-detail"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="jb-detail-modal"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="jb-detail-row"]')).toHaveLength(2)
  })

  it('the 💬 button reuses the existing project-bound-thread resolver (useJobActions.handleMessages), not a new nav path', async () => {
    h.getActive.mockResolvedValue({ data: [NEEDS_INPUT_PROJECT] })
    h.listAgentJobs.mockResolvedValue(envelope(NEEDS_INPUT_AGENTS))

    const wrapper = mountView()
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="jb-btn-hub"]').trigger('click')
    expect(handleMessagesMock).toHaveBeenCalledWith({}, 'proj-1')
  })
})

describe('JobsViewportView density (FE-9678)', () => {
  function memoryStorage() {
    const map = new Map()
    return {
      getItem: (k) => (map.has(k) ? map.get(k) : null),
      setItem: (k, v) => map.set(k, String(v)),
      removeItem: (k) => map.delete(k),
      clear: () => map.clear(),
    }
  }

  let originalStorage
  beforeEach(() => {
    originalStorage = window.localStorage
    window.localStorage = memoryStorage()
  })
  afterEach(() => {
    window.localStorage = originalStorage
  })

  it('renders the View segment, labelled View, with Compact pressed by default', async () => {
    h.getActive.mockResolvedValue({ data: [NEEDS_INPUT_PROJECT] })
    const wrapper = mountView()
    await flushPromises()
    const detailed = wrapper.find('[data-testid="jobs-density-detailed"]')
    const compact = wrapper.find('[data-testid="jobs-density-compact"]')
    expect(wrapper.find('[data-testid="jobs-view-label"]').text()).toBe('View')
    expect(wrapper.find('[data-testid="jobs-view-switch"]').attributes('aria-label')).toBe('View')
    expect(detailed.exists()).toBe(true)
    expect(compact.exists()).toBe(true)
    expect(detailed.attributes('aria-pressed')).toBe('false')
    expect(compact.attributes('aria-pressed')).toBe('true')
  })

  it('Compact folds every card, Detailed opens them all, and the choice is remembered', async () => {
    const quiet = { ...NEEDS_INPUT_PROJECT, id: 'p-quiet', taxonomy_alias: 'FE-0002', name: 'Quiet one' }
    h.getActive.mockResolvedValue({ data: [NEEDS_INPUT_PROJECT, quiet] })
    h.listAgentJobs.mockImplementation((pid) =>
      Promise.resolve(
        envelope(
          pid === 'p-quiet'
            ? [{ agent_id: 'q-or', job_id: 'qj', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working', steps: { completed: 1, total: 3 } }]
            : [{ agent_id: 'n-or', job_id: 'nj', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'silent', steps: { completed: 1, total: 3 } }],
        ),
      ),
    )
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.findAll('[data-testid="jb-summary"]')).toHaveLength(2)

    await wrapper.find('[data-testid="jobs-density-detailed"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="jb-summary"]')).toHaveLength(0)
    expect(window.localStorage.getItem('jobs.density.v2')).toBe('detailed')

    await wrapper.find('[data-testid="jobs-density-compact"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="jb-summary"]')).toHaveLength(2)
    expect(window.localStorage.getItem('jobs.density.v2')).toBe('compact')
  })
})

describe('JobsViewportView sides (FE-9679)', () => {
  const ACTIVATED = { id: 'p-act', taxonomy_alias: 'BE-1', name: 'Never staged', status: 'active', staging_status: null, implementation_launched_at: null }
  const STAGED = { id: 'p-staged', taxonomy_alias: 'BE-2', name: 'Waiting for the go', status: 'active', staging_status: 'staging_complete', implementation_launched_at: null }
  const IMPL = { id: 'p-impl', taxonomy_alias: 'BE-3', name: 'Running', status: 'active', implementation_launched_at: '2026-08-30T23:02:00Z' }

  it('the side segment counts each side; Implementation is the landing when anything runs', async () => {
    h.getActive.mockResolvedValue({ data: [ACTIVATED, STAGED, IMPL] })
    h.listAgentJobs.mockImplementation((pid) =>
      Promise.resolve(envelope(pid === 'p-impl' ? [{ agent_display_name: 'orchestrator', agent_name: 'orchestrator', status: 'working' }] : [])),
    )
    const wrapper = mountView()
    await flushPromises()
    await flushPromises()

    const staging = wrapper.find('[data-testid="jobs-side-staging"]')
    const impl = wrapper.find('[data-testid="jobs-side-implementation"]')
    expect(staging.text()).toContain('2')
    expect(impl.text()).toContain('1')
    expect(impl.attributes('aria-pressed')).toBe('true')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Running')
    expect(wrapper.find('[data-testid="jobs-filter-needs-input"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jobs-filter-staged"]').exists()).toBe(false)

    await staging.trigger('click')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(2)
    expect(wrapper.find('[data-testid="jobs-filter-staged"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jobs-filter-needs-input"]').exists()).toBe(false)
    await wrapper.find('[data-testid="jobs-filter-staged"]').trigger('click')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Waiting for the go')
  })

  it('with nothing running the board lands on Staging', async () => {
    h.getActive.mockResolvedValue({ data: [ACTIVATED] })
    const wrapper = mountView()
    await flushPromises()
    await flushPromises()
    expect(wrapper.find('[data-testid="jobs-side-staging"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
  })

  it('a card asking to edit its description opens the one project edit dialog on the board', async () => {
    h.getActive.mockResolvedValue({ data: [ACTIVATED] })
    const wrapper = mountView()
    await flushPromises()
    await flushPromises()
    expect(wrapper.find('[data-testid="jobs-board-edit-dialog"]').exists()).toBe(false)
    await wrapper.find('[data-testid="jb-edit-description"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="jobs-board-edit-dialog"]').exists()).toBe(true)
  })

  const FULL_PROJECT = {
    id: 'p-full',
    taxonomy_alias: 'BE-9707',
    name: 'The real project name',
    description: 'The real description body.',
    mission: 'The real orchestrator mission.',
    status: 'active',
    project_type_id: 'type-1',
    series_number: 42,
    subseries: 'a',
    implementation_launched_at: null,
  }

  it('the pencil opens Edit Project PRE-FILLED with the project current fields, not empty', async () => {
    h.getActive.mockResolvedValue({ data: [FULL_PROJECT] })
    const wrapper = mountView()
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="jb-edit-description"]').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(wrapper.find('[aria-label="Project name"]').attributes('modelvalue')).toBe(FULL_PROJECT.name)
    expect(wrapper.find('[aria-label="Project description"]').attributes('modelvalue')).toBe(FULL_PROJECT.description)
    expect(wrapper.find('[aria-label="Orchestrator mission"]').attributes('modelvalue')).toBe(FULL_PROJECT.mission)
  })
})

describe('JobsViewportView all products (FE-9680)', () => {
  function memoryStorage() {
    const map = new Map()
    return {
      getItem: (k) => (map.has(k) ? map.get(k) : null),
      setItem: (k, v) => map.set(k, String(v)),
      removeItem: (k) => map.delete(k),
      clear: () => map.clear(),
    }
  }
  let originalStorage
  beforeEach(() => {
    originalStorage = window.localStorage
    window.localStorage = memoryStorage()
    const productStore = useProductStore()
    productStore.products = [
      { id: 'prod-a', name: 'Alpha' },
      { id: 'prod-b', name: 'Beta' },
    ]
    productStore.currentProductId = 'prod-a'
    productStore.currentProduct = { id: 'prod-a', name: 'Alpha' }
  })
  afterEach(() => {
    window.localStorage = originalStorage
  })

  const A_RUNNING = { id: 'a-run', taxonomy_alias: 'BE-1', name: 'Alpha running', status: 'active', product_id: 'prod-a', implementation_launched_at: '2026-08-30T23:02:00Z' }
  const B_RUNNING = { id: 'b-run', taxonomy_alias: 'BE-2', name: 'Beta running', status: 'active', product_id: 'prod-b', implementation_launched_at: '2026-08-31T01:00:00Z' }
  const B_STAGING = { id: 'b-stage', taxonomy_alias: 'BE-3', name: 'Beta waiting', status: 'active', product_id: 'prod-b', staging_status: null, implementation_launched_at: null }

  it('lands on All: reads every product, one group per product, most recent first', async () => {
    h.getActive.mockResolvedValue({ data: [A_RUNNING, B_RUNNING, B_STAGING] })
    h.listAgentJobs.mockResolvedValue(envelope([{ agent_display_name: 'orchestrator', agent_name: 'orchestrator', status: 'working' }]))
    const wrapper = mountView()
    await flushPromises()
    await flushPromises()

    expect(h.getActive).toHaveBeenCalled()
    expect(h.getActive.mock.calls[0][0]).toBeFalsy()
    const groups = wrapper.findAll('[data-testid="jobs-product-group"]')
    expect(groups).toHaveLength(2)
    expect(groups[0].find('[data-testid="jobs-product-group-name"]').text()).toBe('Beta')
    expect(groups[1].find('[data-testid="jobs-product-group-name"]').text()).toBe('Alpha')
    expect(groups[0].findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(groups[0].find('[data-testid="jobs-product-group-counts"]').text()).toMatch(/1 staging/)
    expect(groups[0].find('[data-testid="jobs-product-group-counts"]').text()).toMatch(/1 implementing/)
    expect(wrapper.text()).toContain('across 2 products')
  })

  it('a product with nothing on this side shows one quiet line, never an empty grid', async () => {
    h.getActive.mockResolvedValue({ data: [A_RUNNING, B_STAGING] })
    h.listAgentJobs.mockResolvedValue(envelope([]))
    const wrapper = mountView()
    await flushPromises()
    await flushPromises()
    await wrapper.find('[data-testid="jobs-side-staging"]').trigger('click')
    const alpha = wrapper.findAll('[data-testid="jobs-product-group"]').find((g) => g.text().includes('Alpha'))
    expect(alpha.find('[data-testid="jobs-product-group-quiet"]').exists()).toBe(true)
    expect(alpha.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(0)
  })

  it('the group chevron folds the product to its header and is remembered', async () => {
    h.getActive.mockResolvedValue({ data: [A_RUNNING, B_RUNNING] })
    h.listAgentJobs.mockResolvedValue(envelope([]))
    const wrapper = mountView()
    await flushPromises()
    await flushPromises()
    const beta = wrapper.findAll('[data-testid="jobs-product-group"]')[0]
    expect(beta.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    await beta.find('[data-testid="jobs-product-group-fold"]').trigger('click')
    expect(beta.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(0)
    expect(beta.find('[data-testid="jobs-product-group-name"]').text()).toBe('Beta')
    expect(JSON.parse(window.localStorage.getItem('jobs.groupFold'))).toContain('prod-b')
  })

  it('narrowed to a product, the board reads that product and shows no groups', async () => {
    useJobsScopeStore().selectProduct()
    h.getActive.mockResolvedValue({ data: [A_RUNNING] })
    h.listAgentJobs.mockResolvedValue(envelope([]))
    const wrapper = mountView()
    await flushPromises()
    await flushPromises()
    expect(h.getActive.mock.calls[0][0]).toBe('prod-a')
    expect(wrapper.findAll('[data-testid="jobs-product-group"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('for Alpha')
  })
})
