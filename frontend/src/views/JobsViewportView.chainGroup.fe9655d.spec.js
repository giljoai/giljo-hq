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

function project(id, alias) {
  return { id, taxonomy_alias: alias, name: `Project ${alias}`, status: 'active', staging_status: null, product_id: 'prod-1' }
}

let pinia
async function mountBoard(path = '/jobs-overview') {
  await router.push(path)
  const wrapper = mount(JobsViewportView, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const solo = project('solo', 'FE-0100')
  const m1 = project('m1', 'FE-0201')
  const m2 = project('m2', 'FE-0202')
  server.projects = { solo, m1, m2 }
  server.active = [solo, m2, m1]
  server.runs = [
    {
      id: 'run-1',
      project_ids: ['m2', 'm1'],
      resolved_order: ['m1', 'm2'],
      current_index: 0,
      status: 'pending',
      locked: false,
      execution_mode: 'multi_terminal',
      project_statuses: { m1: 'pending', m2: 'pending' },
      chain_mission: '# Chain mission: Two steps',
    },
  ]
  Element.prototype.scrollIntoView = vi.fn()
})

describe('Jobs board chain groups (FE-9655d)', () => {
  it('renders the chain as one group with its members in run order, and the rest as loose cards', async () => {
    const wrapper = await mountBoard()
    const groups = wrapper.findAll('[data-testid="chain-group"]')
    expect(groups).toHaveLength(1)
    expect(groups[0].find('[data-testid="chain-group-name"]').text()).toBe('Two steps')
    expect(groups[0].findAll('[data-testid="chain-group-member"]').map((m) => m.attributes('data-project-id'))).toEqual([
      'm1',
      'm2',
    ])
    const loose = wrapper.findAll('[data-testid="jobs-board-grid"] [data-testid="jb-tax-pill"]')
    expect(loose.map((pill) => pill.text())).toEqual(['FE-0100'])
    wrapper.unmount()
  })

  it('shows the board, not the empty state, when only a chain is in flight', async () => {
    server.active = []
    const wrapper = await mountBoard()
    expect(wrapper.find('[data-testid="jobs-board-empty"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="chain-group"]')).toHaveLength(1)
    wrapper.unmount()
  })

  it('?run=<id> highlights that group and brings it into view', async () => {
    const wrapper = await mountBoard('/jobs-overview?run=run-1')
    const group = wrapper.find('[data-testid="chain-group"]')
    expect(group.classes()).toContain('cg--highlight')
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('offers no "Launch staged" selection any more (the chain header starts a chain)', async () => {
    const wrapper = await mountBoard()
    expect(wrapper.find('[data-testid="jobs-launch-bar"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid^="jb-select-"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
