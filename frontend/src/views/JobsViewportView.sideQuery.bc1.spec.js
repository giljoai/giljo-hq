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
const onSide = (w) => (tab(w, 'staging').attributes('aria-pressed') === 'true' ? 'staging' : 'implementation')

const link = (query) => router.push({ name: 'JobsViewport', query })

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  server.runs = []
  server.active = [waiting('w1', 'FE-0100'), done('d1', 'FE-0300')]
  Element.prototype.scrollIntoView = vi.fn()
})

describe('the board follows ?side= when the address changes', () => {
  it('on Staging, the address changes to side=implementation: the board shows Implementation', async () => {
    const w = await mountBoard()
    expect(onSide(w)).toBe('staging')
    await link({ side: 'implementation' })
    await flushPromises()
    expect(onSide(w)).toBe('implementation')
    expect(w.find('[data-testid="jobs-done-group"]').exists()).toBe(true)
    w.unmount()
  })

  it('second press: press, pick Staging by hand, press again: Implementation again', async () => {
    const w = await mountBoard()
    await link({ side: 'implementation' })
    await flushPromises()
    expect(onSide(w)).toBe('implementation')
    await tab(w, 'staging').trigger('click')
    await flushPromises()
    expect(onSide(w)).toBe('staging')
    expect(router.currentRoute.value.query.side).toBe('staging')
    await link({ side: 'implementation' })
    await flushPromises()
    expect(onSide(w)).toBe('implementation')
    w.unmount()
  })

  it('an invalid side value changes nothing', async () => {
    const w = await mountBoard()
    await link({ side: 'sideways' })
    await flushPromises()
    expect(onSide(w)).toBe('staging')
    expect(tab(w, 'staging').exists()).toBe(true)
    w.unmount()
  })

  it('scope and side together at first open: scope=all is stripped, side is kept and honoured', async () => {
    const w = await mountBoard({ scope: 'all', side: 'implementation' })
    expect(onSide(w)).toBe('implementation')
    expect(router.currentRoute.value.query.scope).toBeUndefined()
    expect(router.currentRoute.value.query.side).toBe('implementation')
    w.unmount()
  })
})
