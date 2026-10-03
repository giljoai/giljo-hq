import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const server = vi.hoisted(() => ({ active: [], runs: [] }))

vi.mock('@/services/api', () => {
  const ok = (data) => Promise.resolve({ data })
  const api = {
    projects: {
      getActive: () => ok(server.active.map((p) => ({ ...p }))),
      get: () => ok({}),
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
  server.active = [live('solo', 'FE-0100'), done('d1', 'FE-0300'), done('d2', 'FE-0301')]
  server.runs = []
  Element.prototype.scrollIntoView = vi.fn()
})

describe('Done, not reviewed group (FE-9708)', () => {
  it('shows a folded group with the count and mounts no card until opened', async () => {
    const wrapper = await mountBoard()
    const group = wrapper.find('[data-testid="jobs-done-group"]')
    expect(group.exists()).toBe(true)
    expect(group.find('[data-testid="jobs-done-group-count"]').text()).toContain('2')
    expect(group.text()).toContain('Done, not reviewed')
    expect(group.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(0)
    wrapper.unmount()
  })

  it('opening it shows the normal cards, each with its Review button; the live card stays outside', async () => {
    const wrapper = await mountBoard()
    await wrapper.find('[data-testid="jobs-done-group-toggle"]').trigger('click')
    await flushPromises()
    const cards = wrapper.findAll('[data-testid="jobs-done-group"] [data-testid="jobs-board-card-wrap"]')
    expect(cards).toHaveLength(2)
    for (const card of cards) expect(card.find('[data-testid="jb-btn-review"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="jobs-board-card-wrap"]')).toHaveLength(3)
    wrapper.unmount()
  })

  it('the Review counter counts the two unreviewed projects in the folded group', async () => {
    const wrapper = await mountBoard()
    expect(wrapper.find('[data-testid="jobs-side-implementation"]').text()).toContain('1')
    expect(wrapper.find('[data-testid="jobs-status-review"]').text()).toMatch(/Review\s*2/)
    wrapper.unmount()
  })

  it('shows the board, not the empty state, when only unreviewed projects exist', async () => {
    server.active = [done('d1', 'FE-0300')]
    const wrapper = await mountBoard()
    expect(wrapper.find('[data-testid="jobs-board-empty"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jobs-done-group"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('a chain member stays in its chain group, not in the done group', async () => {
    server.active = [done('m1', 'FE-0201')]
    server.runs = [
      {
        id: 'run-1',
        project_ids: ['m1'],
        resolved_order: ['m1'],
        current_index: 0,
        status: 'running',
        locked: false,
        execution_mode: 'multi_terminal',
        project_statuses: { m1: 'completed' },
        chain_mission: '# Chain mission: One step',
      },
    ]
    const wrapper = await mountBoard()
    expect(wrapper.find('[data-testid="jobs-done-group"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="chain-group-member"]')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('Header counts (FE-9708)', () => {
  it('puts the count line under the subtitle and drops the stale phrase', async () => {
    const wrapper = await mountBoard()
    const line = wrapper.find('[data-testid="jobs-board-count-line"]')
    expect(line.exists()).toBe(true)
    expect(line.text()).toContain('1 in flight')
    expect(line.text()).toContain('2 done, not reviewed')
    expect(wrapper.find('[data-testid="jobs-board-toolbar"]').text()).not.toContain('in flight')
    expect(wrapper.text()).not.toContain('reviewed projects leave the board')
    wrapper.unmount()
  })
})
