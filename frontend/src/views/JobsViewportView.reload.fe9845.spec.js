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

beforeEach(async () => {
  await router.replace({ name: 'Root', query: {} })
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

import { useJobsScopeStore } from '@/stores/jobsScope'

describe('Board scope and side survive a reload (FE-9845)', () => {
  it('no query: lands on All and the landing side, and writes nothing to the URL', async () => {
    server.active = [STAGED, RUNNING]
    const wrapper = await mountAt()
    expect(useJobsScopeStore().allProducts).toBe(true)
    expect(sideOn(wrapper)).toBe('staging')
    expect(router.currentRoute.value.query.scope).toBeUndefined()
    wrapper.unmount()
  })

  it('?scope=product restores the narrowed board', async () => {
    server.active = [RUNNING]
    const wrapper = await mountAt({ scope: 'product' })
    expect(useJobsScopeStore().allProducts).toBe(false)
    wrapper.unmount()
  })

  it('narrowing the board writes scope=product; widening it removes it', async () => {
    server.active = [RUNNING]
    const wrapper = await mountAt()
    const scope = useJobsScopeStore()
    scope.selectProduct()
    await flushPromises()
    expect(router.currentRoute.value.query.scope).toBe('product')
    scope.selectAll()
    await flushPromises()
    expect(router.currentRoute.value.query.scope).toBeUndefined()
    wrapper.unmount()
  })

  it('?side=implementation beats the staging landing', async () => {
    server.active = [STAGED, RUNNING]
    const wrapper = await mountAt({ side: 'implementation' })
    expect(sideOn(wrapper)).toBe('implementation')
    wrapper.unmount()
  })

  it('picking a side writes it to the URL and keeps the other query keys', async () => {
    server.active = [STAGED, RUNNING]
    const wrapper = await mountAt({ scope: 'product' })
    await wrapper.find('[data-testid="jobs-side-implementation"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toMatchObject({ side: 'implementation', scope: 'product' })
    wrapper.unmount()
  })

  it('an unknown side or scope value is ignored', async () => {
    server.active = [STAGED, RUNNING]
    const wrapper = await mountAt({ side: 'bogus', scope: 'bogus' })
    expect(sideOn(wrapper)).toBe('staging')
    expect(useJobsScopeStore().allProducts).toBe(true)
    wrapper.unmount()
  })

  it('a Play arrival (?project=) still wins over a stored side', async () => {
    server.active = [ACTIVATED, RUNNING]
    const wrapper = await mountAt({ project: 'p-act', side: 'implementation' })
    expect(sideOn(wrapper)).toBe('staging')
    wrapper.unmount()
  })
})
