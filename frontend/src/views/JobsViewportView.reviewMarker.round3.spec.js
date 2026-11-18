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
    agentJobs: {
      list: () => ok({ jobs: [], total: 0, limit: 50, offset: 0 }),
      listMany: () => ok({ jobs: [], total: 0, limit: 500, offset: 0 }),
    },
    settings: { getHeadlessLaunch: () => ok({ allow_headless_launch: true }) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import JobsViewportView from './JobsViewportView.vue'
import { useProjectStore } from '@/stores/projects'

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

const waiting = (id, alias) => ({
  id, taxonomy_alias: alias, name: `Project ${alias}`, status: 'active', staging_status: 'staging_complete',
  product_id: 'prod-1', implementation_launched_at: null,
})
const running = (id, alias) => ({ ...waiting(id, alias), staging_status: null, implementation_launched_at: '2026-09-30T00:00:00Z' })
const done = (id, alias) => ({
  ...running(id, alias), status: 'completed', completed_at: '2026-10-01T00:00:00Z', reviewed_at: null, review_pending: true,
})

let pinia
async function mountBoard(query = {}) {
  await router.push({ name: 'JobsViewport', query })
  const wrapper = mount(JobsViewportView, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}
const tab = (w, side) => w.find(`[data-testid="jobs-side-${side}"]`)
const marker = (w) => w.find('[data-testid="jobs-side-implementation-review"]')
const onSide = (w) => (tab(w, 'staging').attributes('aria-pressed') === 'true' ? 'staging' : 'implementation')

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  server.runs = []
  Element.prototype.scrollIntoView = vi.fn()
})

describe('finished project is findable from the Staging side', () => {
  it('one project waiting + one done-not-reviewed: Staging shown, Implementation tab marks the review', async () => {
    server.active = [waiting('w1', 'FE-0100'), done('d1', 'FE-0300')]
    const w = await mountBoard()
    expect(onSide(w)).toBe('staging')
    expect(tab(w, 'implementation').find('.jb-filter-n').text()).toBe('0')
    expect(marker(w).exists()).toBe(true)
    expect(marker(w).text()).toBe('1 to review')
    expect(tab(w, 'implementation').text()).toContain('1 to review')
    w.unmount()
  })

  it('only a done-not-reviewed project: lands on Implementation, card visible, marker agrees', async () => {
    server.active = [done('d1', 'FE-0300')]
    const w = await mountBoard()
    expect(onSide(w)).toBe('implementation')
    expect(w.find('[data-testid="jobs-done-group"]').exists()).toBe(true)
    expect(marker(w).text()).toBe('1 to review')
    w.unmount()
  })

  it('no done project: no marker', async () => {
    server.active = [waiting('w1', 'FE-0100'), running('r1', 'FE-0200')]
    const w = await mountBoard()
    expect(marker(w).exists()).toBe(false)
    expect(tab(w, 'implementation').find('.jb-filter-n').text()).toBe('1')
    w.unmount()
  })

  it('an implementing project is counted once: in the number, not in the marker', async () => {
    server.active = [running('r1', 'FE-0200'), done('d1', 'FE-0300'), done('d2', 'FE-0301')]
    const w = await mountBoard()
    expect(tab(w, 'implementation').find('.jb-filter-n').text()).toBe('1')
    expect(marker(w).text()).toBe('2 to review')
    w.unmount()
  })

  it('?side=implementation opens the Implementation side even with a project waiting', async () => {
    server.active = [waiting('w1', 'FE-0100'), done('d1', 'FE-0300')]
    const w = await mountBoard({ side: 'implementation' })
    expect(onSide(w)).toBe('implementation')
    expect(w.find('[data-testid="jobs-done-group"]').exists()).toBe(true)
    w.unmount()
  })

  it('an agent finishing a project while the person watches Staging does not move the board', async () => {
    server.active = [waiting('w1', 'FE-0100'), running('r1', 'FE-0200')]
    const w = await mountBoard()
    expect(onSide(w)).toBe('staging')
    server.active = [waiting('w1', 'FE-0100'), done('r1', 'FE-0200')]
    await useProjectStore().fetchActiveProject()
    await flushPromises()
    await flushPromises()
    expect(onSide(w)).toBe('staging')
    w.unmount()
  })
})
