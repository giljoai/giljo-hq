/**
 * JobsViewportView.spec.js — FE-9548
 *
 * The Jobs board, rebuilt strictly to design mock jobs-board-proposal-v4.html
 * after FE-9525d shipped with none of the house design-system treatments
 * applied. Reads the SAME store field (activeProjectsMeta) the
 * LaunchRedirectView plural-redirect test drives.
 *
 * FE-9545 REGRESSION lesson carried forward: the server's real
 * /api/agent-jobs/ response is a PAGINATED ENVELOPE ({jobs, total, limit,
 * offset}), never a bare array -- every agent-jobs mock below uses that
 * shape, matching agent_jobs/models.py's JobListResponse.response_model
 * rather than a shape read off the component.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
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

// The paginated envelope FE-9545 fixed the code to actually read.
function envelope(jobs) {
  return { data: { jobs, total: jobs.length, limit: 50, offset: 0 } }
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  h.listAgentJobs.mockResolvedValue(envelope([]))
})

// The global v-tooltip stub (tests/setup.js) renders only the default slot,
// hiding activator-slotted content (JobsBoardCard's title/badge tooltips use
// #activator). Override with a stub rendering both, mirroring
// JobsBoardCard.spec.js / AgentRow.spec.js / JobsTab.spec.js.
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

    expect(wrapper.find('[data-testid="jobs-board-empty"]').text()).toContain('Nothing in flight for this product')
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

    const cards = wrapper.findAll('[data-testid="jobs-board-card-wrap"]')
    expect(cards).toHaveLength(2)
    expect(wrapper.text()).toContain('Flip the headless launch fence')
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

  // FE-9551: an activated-but-never-staged project (staging_status
  // null/undefined) and a project mid-staging (staging_status 'staging')
  // must both be filterable -- a state a card can display but the filter
  // can't reach is a hole. Also pins the honest Activated label replacing
  // the old catch-all "Staged" mislabeling.
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
