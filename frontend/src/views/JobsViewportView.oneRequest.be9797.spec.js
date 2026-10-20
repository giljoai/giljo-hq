import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const server = vi.hoisted(() => ({ active: [], jobs: {}, cap: null }))
const ws = vi.hoisted(() => ({ handlers: {} }))
const h = vi.hoisted(() => ({ list: null, listMany: null, notify: null }))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: (type, fn) => {
      ;(ws.handlers[type] ||= new Set()).add(fn)
      return () => ws.handlers[type].delete(fn)
    },
    off: () => {},
    onConnectionChange: () => () => {},
  }),
}))

vi.mock('@/services/api', async () => {
  const { vi: v } = await import('vitest')
  const ok = (data) => Promise.resolve({ data })
  h.list = v.fn((pid) => {
    const jobs = (server.jobs[pid] || []).map((job) => ({ ...job, project_id: pid }))
    return ok({ jobs, total: jobs.length, limit: 100, offset: 0 })
  })
  h.listMany = v.fn((ids) => {
    const all = ids.flatMap((pid) =>
      (server.jobs[pid] || []).map((job) => ({ ...job, project_id: pid })),
    )
    const jobs = server.cap === null ? all : all.slice(0, server.cap)
    return ok({ jobs, total: all.length, limit: 500, offset: 0 })
  })
  const api = {
    projects: {
      getActive: () => ok(server.active.map((p) => ({ ...p }))),
      getOrchestrator: () => ok({ orchestrator: null }),
    },
    sequenceRuns: { list: () => ok([]) },
    agentJobs: { list: (...a) => h.list(...a), listMany: (...a) => h.listMany(...a) },
    settings: { getHeadlessLaunch: () => ok({ allow_headless_launch: true }) },
    git: { getSettings: () => ok({ enabled: false }) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/utils/notifyFailure', () => ({ notifyFailure: (...a) => h.notify?.(...a) }))

import JobsViewportView from './JobsViewportView.vue'
import { normalizeWebsocketPayload } from '@/utils/normalizeWebsocketPayload'

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
const tooltipStub = {
  template: '<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>',
}

function running(id, alias) {
  return {
    id,
    taxonomy_alias: alias,
    name: `Project ${alias}`,
    status: 'active',
    staging_status: 'staging_complete',
    execution_mode: 'multi_terminal',
    product_id: 'prod-1',
    implementation_launched_at: '2026-10-15T10:00:00Z',
  }
}
const agent = (id, name) => ({
  agent_id: id,
  job_id: `j-${id}`,
  agent_display_name: name,
  agent_name: name,
  status: 'working',
})

function fire(raw) {
  const { type, payload } = normalizeWebsocketPayload(raw)
  for (const fn of ws.handlers[type] || []) fn(payload)
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 400))
  await flushPromises()
  await flushPromises()
}

async function mountBoard() {
  await router.push('/jobs-overview')
  const wrapper = mount(JobsViewportView, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
  await flushPromises()
  await flushPromises()
  await wrapper.find('[data-testid="jobs-side-implementation"]').trigger('click')
  await flushPromises()
  return wrapper
}

function agentCount(wrapper, alias) {
  const card = wrapper
    .findAll('[data-testid="jobs-board-card-wrap"]')
    .find((c) => c.find('[data-testid="jb-tax-pill"]').text() === alias)
  return Number(card.find('[data-testid="jb-stat-agents"]').text())
}

let pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  ws.handlers = {}
  server.cap = null
  h.notify = vi.fn()
  window.localStorage.getItem.mockImplementation((k) =>
    k === 'jobs.density.v2' ? 'detailed' : null,
  )
  Element.prototype.scrollIntoView = vi.fn()
  server.active = [running('p1', 'BE-0001'), running('p2', 'BE-0002'), running('p3', 'BE-0003')]
  server.jobs = {
    p1: [agent('a1', 'orchestrator'), agent('a2', 'implementer')],
    p2: [agent('b1', 'orchestrator')],
    p3: [],
  }
})

describe('BE-9797: the Jobs board reads every card in one request', () => {
  it('the initial load asks once for all three projects and never per project', async () => {
    const wrapper = await mountBoard()

    expect(h.listMany).toHaveBeenCalledTimes(1)
    expect([...h.listMany.mock.calls[0][0]].sort()).toEqual(['p1', 'p2', 'p3'])
    expect(h.list).toHaveBeenCalledTimes(0)
    expect(agentCount(wrapper, 'BE-0001')).toBe(2)
    expect(agentCount(wrapper, 'BE-0002')).toBe(1)
    wrapper.unmount()
  })

  it('a project with no agents still gets its entry, so a live re-read does not ask for it again', async () => {
    const wrapper = await mountBoard()
    h.listMany.mockClear()
    h.list.mockClear()

    fire({ type: 'project:mission_updated', data: { tenant_key: 't' } })
    await settle()

    expect(h.listMany).toHaveBeenCalledTimes(0)
    expect(h.list).toHaveBeenCalledTimes(0)
    wrapper.unmount()
  })

  it('a live re-read naming two projects asks once for both', async () => {
    const wrapper = await mountBoard()
    h.listMany.mockClear()
    h.list.mockClear()
    server.jobs.p2 = [agent('b1', 'orchestrator'), agent('b2', 'tester')]

    fire({ type: 'project:mission_updated', data: { project_id: 'p1', tenant_key: 't' } })
    fire({ type: 'project:staging_complete', data: { project_id: 'p2', tenant_key: 't' } })
    await settle()

    expect(h.listMany).toHaveBeenCalledTimes(1)
    expect([...h.listMany.mock.calls[0][0]].sort()).toEqual(['p1', 'p2'])
    expect(h.list).toHaveBeenCalledTimes(0)
    expect(agentCount(wrapper, 'BE-0002')).toBe(2)
    wrapper.unmount()
  })

  it("one card's own agent event still re-reads only that card", async () => {
    const wrapper = await mountBoard()
    h.listMany.mockClear()
    h.list.mockClear()

    fire({ type: 'agent:status_changed', data: { project_id: 'p2', tenant_key: 't' } })
    await settle()

    expect(h.list).toHaveBeenCalledTimes(1)
    expect(h.list).toHaveBeenCalledWith('p2')
    expect(h.listMany).toHaveBeenCalledTimes(0)
    wrapper.unmount()
  })

  it('a reply cut short by the page size falls back to one read per card rather than showing missing agents', async () => {
    server.cap = 2
    const wrapper = await mountBoard()

    expect(h.listMany).toHaveBeenCalledTimes(1)
    expect(h.list).toHaveBeenCalledTimes(3)
    expect(agentCount(wrapper, 'BE-0001')).toBe(2)
    expect(agentCount(wrapper, 'BE-0002')).toBe(1)
    wrapper.unmount()
  })

  it('a failed read empties every card it covered and raises one notice', async () => {
    h.listMany.mockImplementationOnce(() => Promise.reject(new Error('boom')))
    const wrapper = await mountBoard()

    expect(h.notify).toHaveBeenCalledTimes(1)
    expect(h.list).toHaveBeenCalledTimes(0)
    wrapper.unmount()
  })
})
