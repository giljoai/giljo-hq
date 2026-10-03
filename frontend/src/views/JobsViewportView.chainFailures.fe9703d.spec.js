import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const server = vi.hoisted(() => ({ runsFail: false, failIds: new Set(), runs: [], projects: {} }))

vi.mock('@/services/api', () => {
  const ok = (data) => Promise.resolve({ data })
  const fail = (message) =>
    Promise.reject(Object.assign(new Error('x'), { isAxiosError: true, response: { status: 500, data: { message } } }))
  const api = {
    projects: {
      getActive: () => ok([]),
      get: (id) => (server.failIds.has(id) ? fail('project read failed') : ok({ ...server.projects[id] })),
      getOrchestrator: () => ok({ orchestrator: null }),
    },
    sequenceRuns: { list: () => (server.runsFail ? fail('chain list unavailable') : ok(server.runs)) },
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

const project = (id, alias) => ({ id, taxonomy_alias: alias, name: `Project ${alias}`, status: 'active', staging_status: null, product_id: 'prod-1', description: '' })

async function mountBoard() {
  await router.push('/jobs-overview')
  const wrapper = mount(JobsViewportView, {
    attachTo: document.body,
    global: {
      plugins: [createPinia(), router],
      stubs: { 'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' } },
    },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(console, 'error').mockImplementation(() => {})
  server.runsFail = false
  server.failIds = new Set()
  server.projects = { m1: project('m1', 'FE-0201'), m2: project('m2', 'FE-0202') }
  server.runs = [
    {
      id: 'run-1',
      project_ids: ['m1', 'm2'],
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

describe('Jobs board: chain failures are shown', () => {
  it('a failed chain list read is shown with the reason', async () => {
    server.runsFail = true
    const wrapper = await mountBoard()
    const err = wrapper.find('[data-testid="jobs-board-chain-error"]')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('chain list unavailable')
    wrapper.unmount()
  })

  it('a member whose project failed to load says so in its step', async () => {
    server.failIds = new Set(['m2'])
    const wrapper = await mountBoard()
    const members = wrapper.findAll('[data-testid="chain-group-member"]')
    expect(members).toHaveLength(2)
    expect(members[0].find('[data-testid="chain-member-load-error"]').exists()).toBe(false)
    expect(members[1].find('[data-testid="chain-member-load-error"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
