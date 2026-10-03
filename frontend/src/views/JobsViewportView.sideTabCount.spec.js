import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const server = vi.hoisted(() => ({ active: [], runs: [], projects: {} }))

vi.mock('@/services/api', () => {
  const ok = (data) => Promise.resolve({ data })
  const api = {
    projects: {
      getActive: () => ok(server.active.map((p) => ({ ...p }))),
      get: (id) => ok({ ...server.projects[id] }),
      getOrchestrator: () => ok({ orchestrator: null }),
    },
    sequenceRuns: { list: () => ok(server.runs) },
    agentJobs: { list: () => ok({ jobs: [], total: 0, limit: 50, offset: 0 }) },
    settings: { getHeadlessLaunch: () => ok({ allow_headless_launch: true }) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))
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

function card(id, alias, product, extra = {}) {
  return {
    id,
    taxonomy_alias: alias,
    name: `Project ${alias}`,
    status: 'active',
    staging_status: 'staging_complete',
    product_id: product,
    implementation_launched_at: null,
    ...extra,
  }
}
const running = (id, alias, product, extra = {}) =>
  card(id, alias, product, { staging_status: null, implementation_launched_at: '2026-09-30T00:00:00Z', ...extra })
function run(id, ids, status, statuses) {
  return {
    id,
    project_ids: ids,
    resolved_order: ids,
    current_index: 0,
    status,
    locked: false,
    execution_mode: 'multi_terminal',
    project_statuses: Object.fromEntries(ids.map((m) => [m, statuses])),
    chain_mission: '# Chain mission',
  }
}

let pinia
async function mountBoard() {
  await router.push('/jobs-overview')
  const wrapper = mount(JobsViewportView, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}
const tabNumber = (wrapper, side) =>
  Number(wrapper.find(`[data-testid="jobs-side-${side}"] .jb-filter-n`).text())
const renderedCards = (wrapper) =>
  wrapper.findAll('[data-testid="jobs-board-card-wrap"]').length +
  wrapper.findAll('[data-testid="chain-group-member"]').length

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const productStore = useProductStore()
  productStore.products = [
    { id: 'prod-1', name: 'Alpha' },
    { id: 'prod-2', name: 'Beta' },
  ]
  productStore.currentProductId = 'prod-1'
  productStore.currentProduct = { id: 'prod-1', name: 'Alpha' }
  const staged = [
    card('a1', 'FE-0301', 'prod-1'),
    card('a2', 'FE-0302', 'prod-1'),
    card('a3', 'FE-0303', 'prod-1'),
    card('b1', 'FE-0401', 'prod-2'),
    card('b2', 'FE-0402', 'prod-2'),
  ]
  const inFlight = [running('c1', 'FE-0501', 'prod-1'), running('c2', 'FE-0502', 'prod-1'), running('c3', 'FE-0503', 'prod-2')]
  server.projects = Object.fromEntries([...staged, ...inFlight].map((m) => [m.id, m]))
  server.active = [
    card('s1', 'FE-0101', 'prod-1'),
    card('s2', 'FE-0102', 'prod-2'),
    running('i1', 'FE-0201', 'prod-1'),
    ...staged,
    ...inFlight,
  ]
  server.runs = [
    run('run-a', ['a1', 'a2', 'a3'], 'pending', 'pending'),
    run('run-b', ['b1', 'b2'], 'pending', 'pending'),
    run('run-c', ['c1', 'c2', 'c3'], 'running', 'running'),
  ]
  Element.prototype.scrollIntoView = vi.fn()
})

describe('Side tab numbers equal the cards rendered', () => {
  it('Staging: loose cards plus every member of each staging chain', async () => {
    const wrapper = await mountBoard()
    await wrapper.find('[data-testid="jobs-side-staging"]').trigger('click')
    await flushPromises()
    expect(renderedCards(wrapper)).toBe(7)
    expect(tabNumber(wrapper, 'staging')).toBe(7)
    wrapper.unmount()
  })

  it('Implementation: loose cards and every member of each running chain', async () => {
    const wrapper = await mountBoard()
    await wrapper.find('[data-testid="jobs-side-implementation"]').trigger('click')
    await flushPromises()
    expect(renderedCards(wrapper)).toBe(4)
    expect(tabNumber(wrapper, 'implementation')).toBe(4)
    wrapper.unmount()
  })
})
