import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const server = vi.hoisted(() => ({ active: [], runs: [], agents: {} }))
const h = vi.hoisted(() => ({ launchImplementation: vi.fn(), launchProject: vi.fn(), copy: vi.fn() }))

vi.mock('@/services/api', async () => {
  const { listManyFrom } = await import('../../tests/helpers/agentJobsListMany')
  const ok = (data) => Promise.resolve({ data })
  const api = {
    projects: {
      getActive: () => ok(server.active.map((p) => ({ ...p }))),
      getOrchestrator: () => ok({ orchestrator: null }),
      launchImplementation: (...a) => h.launchImplementation(...a),
      update: (id, body) => ok({ id, ...body }),
    },
    prompts: { implementation: () => ok({ prompt: 'IMPL PROMPT', agent_count: 1 }) },
    orchestrator: { launchProject: (...a) => h.launchProject(...a) },
    sequenceRuns: { list: () => ok(server.runs) },
    agentJobs: {
      list: (pid) => {
        const jobs = server.agents[pid] || []
        return ok({ jobs, total: jobs.length, limit: 50, offset: 0 })
      },
      listMany: (ids) => listManyFrom(api.agentJobs.list, ids),
    },
    settings: { getHeadlessLaunch: () => ok({ allow_headless_launch: true }) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: h.copy }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import JobsViewportView from './JobsViewportView.vue'
import { useProductStore } from '@/stores/products'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/jobs-overview', name: 'JobsViewport', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})
const tooltipStub = { template: '<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>' }

const base = { status: 'active', product_id: 'prod-1', mission: 'Do it.' }
const ACTIVATED = { ...base, id: 'p-act', taxonomy_alias: 'FE-0001', name: 'Just activated', staging_status: null, implementation_launched_at: null, execution_mode: null }
const STAGED = { ...base, id: 'p-staged', taxonomy_alias: 'FE-0002', name: 'Staged, waiting', staging_status: 'staging_complete', implementation_launched_at: null, execution_mode: 'subagent' }
const RUNNING = { ...base, id: 'p-run', taxonomy_alias: 'FE-0003', name: 'Running', staging_status: 'staging_complete', implementation_launched_at: '2026-10-08T12:00:00Z', execution_mode: 'subagent' }
const WORKING_ORCH = [{ agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working' }]

let pinia
async function mountAt(query = {}) {
  await router.push({ name: 'JobsViewport', query })
  await router.isReady()
  const wrapper = mount(JobsViewportView, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}
const sideOn = (wrapper) =>
  wrapper.find('[data-testid="jobs-side-staging"]').attributes('aria-pressed') === 'true' ? 'staging' : 'implementation'
const cardFor = (wrapper, name) =>
  wrapper.findAll('[data-testid="jobs-board-card-wrap"]').find((c) => c.text().includes(name))

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  window.localStorage.getItem.mockImplementation((k) => (k === 'jobs.density.v2' ? 'detailed' : null))
  const productStore = useProductStore()
  productStore.products = [{ id: 'prod-1', name: 'Alpha' }]
  productStore.currentProductId = 'prod-1'
  productStore.currentProduct = { id: 'prod-1', name: 'Alpha' }
  server.active = []
  server.runs = []
  server.agents = { 'p-run': WORKING_ORCH }
  h.launchImplementation.mockResolvedValue({})
  h.launchProject.mockResolvedValue({})
  h.copy.mockResolvedValue(true)
  Element.prototype.scrollIntoView = vi.fn()
})

describe('Play arrival from the Projects panel', () => {
  it('lands on Staging even while something runs, and highlights that card', async () => {
    server.active = [ACTIVATED, RUNNING]
    const wrapper = await mountAt({ project: 'p-act' })
    expect(sideOn(wrapper)).toBe('staging')
    const card = cardFor(wrapper, 'Just activated')
    expect(card.classes()).toContain('jb-card--arrival')
    wrapper.unmount()
  })

  it('a member of a running chain lands on Implementation, where its chain group is', async () => {
    const member = { ...STAGED, id: 'p-member', taxonomy_alias: 'FE-0004', name: 'Chain member' }
    server.active = [ACTIVATED, member]
    server.runs = [
      {
        id: 'run-1',
        project_ids: ['p-member'],
        resolved_order: ['p-member'],
        current_index: 0,
        status: 'running',
        locked: true,
        execution_mode: 'subagent',
        project_statuses: { 'p-member': 'running' },
      },
    ]
    const wrapper = await mountAt({ project: 'p-member' })
    expect(sideOn(wrapper)).toBe('implementation')
    wrapper.unmount()
  })
})

describe('Plain Jobs open', () => {
  it('lands on Staging when something is mid-staging, even while something runs', async () => {
    server.active = [ACTIVATED, RUNNING]
    const wrapper = await mountAt()
    expect(sideOn(wrapper)).toBe('staging')
    wrapper.unmount()
  })

  it('lands on Implementation when nothing is mid-staging', async () => {
    server.active = [RUNNING]
    const wrapper = await mountAt()
    expect(sideOn(wrapper)).toBe('implementation')
    wrapper.unmount()
  })
})

describe('Launches', () => {
  it('a server-side launch (headless launch_implementation) does not change the tab', async () => {
    server.active = [STAGED]
    const wrapper = await mountAt()
    expect(sideOn(wrapper)).toBe('staging')

    server.active = [{ ...STAGED, implementation_launched_at: '2026-10-08T13:00:00Z' }]
    server.agents = { 'p-staged': WORKING_ORCH }
    await wrapper.vm.fetchBoard()
    await flushPromises()
    expect(sideOn(wrapper)).toBe('staging')
    wrapper.unmount()
  })

  it("the user's own Implement press switches the board to Implementation", async () => {
    server.active = [STAGED, RUNNING]
    const wrapper = await mountAt({ project: 'p-staged' })
    expect(sideOn(wrapper)).toBe('staging')

    await cardFor(wrapper, 'Staged, waiting').find('[data-testid="jbf-implement"]').trigger('click')
    await flushPromises()
    expect(h.launchImplementation).toHaveBeenCalledWith('p-staged')
    expect(sideOn(wrapper)).toBe('implementation')
    wrapper.unmount()
  })
})
