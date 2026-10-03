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

function live(id, alias) {
  return { id, taxonomy_alias: alias, name: `Project ${alias}`, status: 'active', staging_status: null, product_id: 'prod-1', implementation_launched_at: '2026-09-30T00:00:00Z' }
}
function done(id, alias) {
  return {
    ...live(id, alias),
    status: 'completed',
    completed_at: '2026-10-01T00:00:00Z',
    reviewed_at: null,
    review_pending: true,
    implementation_launched_at: '2026-09-30T00:00:00Z',
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

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  Element.prototype.scrollIntoView = vi.fn()
})


function waiting(id, alias) {
  return { ...live(id, alias), implementation_launched_at: null, staging_status: 'staging_complete' }
}
function count(wrapper, key) {
  return wrapper.find(`[data-testid="jobs-status-${key}"]`).text()
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const members = [
    done('m1', 'FE-0201'),
    done('m2', 'FE-0202'),
    live('m3', 'FE-0203'),
    waiting('m4', 'FE-0204'),
    { ...live('m5', 'FE-0205'), status: 'cancelled' },
  ]
  server.projects = Object.fromEntries(members.map((m) => [m.id, m]))
  server.active = [live('solo', 'FE-0100'), done('d1', 'FE-0300')]
  server.runs = [
    {
      id: 'run-1',
      project_ids: ['m1', 'm2', 'm3', 'm4', 'm5'],
      resolved_order: ['m1', 'm2', 'm3', 'm4', 'm5'],
      current_index: 2,
      status: 'running',
      locked: false,
      execution_mode: 'multi_terminal',
      project_statuses: { m1: 'completed', m2: 'completed', m3: 'running', m4: 'pending', m5: 'cancelled' },
      chain_mission: '# Chain mission: Four steps',
    },
  ]
  Element.prototype.scrollIntoView = vi.fn()
})

describe('Status counters count every visible card', () => {
  it('counts loose, chain-member and done-group cards once each', async () => {
    const wrapper = await mountBoard()
    expect(count(wrapper, 'implementing')).toMatch(/Implementing\s*2/)
    expect(count(wrapper, 'review')).toMatch(/Review\s*3/)
    expect(count(wrapper, 'needs-decision')).toMatch(/Needs decision\s*0/)
    expect(count(wrapper, 'needs-attention')).toMatch(/Needs attention\s*0/)
    wrapper.unmount()
  })

  it('does not count a waiting or stopped chain member', async () => {
    const wrapper = await mountBoard()
    const total = ['needs-decision', 'needs-attention', 'implementing', 'review']
      .map((key) => Number(count(wrapper, key).match(/\d+/)[0]))
      .reduce((a, b) => a + b, 0)
    expect(total).toBe(5)
    wrapper.unmount()
  })

  it('counts a member the chain says is done as Review, though its project row is still active', async () => {
    server.runs[0].project_statuses.m3 = 'completed'
    const wrapper = await mountBoard()
    expect(count(wrapper, 'implementing')).toMatch(/Implementing\s*1/)
    expect(count(wrapper, 'review')).toMatch(/Review\s*4/)
    expect(wrapper.find('[data-project-id="m3"] [data-testid="jb-btn-review"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
