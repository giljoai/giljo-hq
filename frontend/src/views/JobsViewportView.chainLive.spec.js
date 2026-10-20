import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const server = vi.hoisted(() => ({ active: [], runs: [], projects: {}, jobs: {} }))
const ws = vi.hoisted(() => ({ handlers: {} }))

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
  const { listManyFrom } = await import('../../tests/helpers/agentJobsListMany')
  const ok = (data) => Promise.resolve({ data })
  const api = {
    projects: {
      getActive: () => ok(server.active.map((id) => ({ ...server.projects[id] }))),
      get: (id) => ok({ ...server.projects[id] }),
      getOrchestrator: () => ok({ orchestrator: null }),
    },
    sequenceRuns: { list: () => ok(server.runs) },
    agentJobs: {
      list: (pid) => {
        const jobs = server.jobs[pid] || []
        return ok({ jobs, total: jobs.length, limit: 50, offset: 0 })
      },
      listMany: (ids) => listManyFrom(api.agentJobs.list, ids),
    },
    settings: { getHeadlessLaunch: () => ok({ allow_headless_launch: true }) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

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
const tooltipStub = { template: '<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>' }

function project(id, alias, extra = {}) {
  return {
    id,
    taxonomy_alias: alias,
    name: `Project ${alias}`,
    description: `About ${alias}`,
    mission: '',
    status: 'active',
    staging_status: null,
    execution_mode: null,
    implementation_launched_at: null,
    product_id: 'prod-1',
    updated_at: '2026-10-08T09:00:00Z',
    ...extra,
  }
}

function serverMoves(id, changes) {
  server.projects[id] = { ...server.projects[id], ...changes }
}

function fire(raw) {
  const { type, payload } = normalizeWebsocketPayload(raw)
  for (const fn of ws.handlers[type] || []) fn(payload)
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 400))
  await flushPromises()
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
  return wrapper
}

function memberCard(wrapper, pid) {
  return wrapper
    .find(`[data-testid="chain-group-member"][data-project-id="${pid}"]`)
    .find('[data-testid="jobs-board-card"]')
}

function looseTitles(wrapper) {
  return wrapper
    .findAll('[data-testid="jb-title"]')
    .filter((title) => !title.element.closest('[data-testid="chain-group"]'))
    .map((title) => title.text())
}

let pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  ws.handlers = {}
  window.localStorage.getItem.mockImplementation((k) => (k === 'jobs.density.v2' ? 'detailed' : null))
  Element.prototype.scrollIntoView = vi.fn()
  server.projects = {
    m1: project('m1', 'FE-0201', {
      staging_status: 'staging_complete',
      execution_mode: 'subagent',
      implementation_launched_at: '2026-10-08T10:00:00Z',
    }),
    m2: project('m2', 'FE-0202'),
    solo: project('solo', 'FE-0100', {
      staging_status: 'staging_complete',
      execution_mode: 'multi_terminal',
      implementation_launched_at: '2026-10-08T10:00:00Z',
    }),
  }
  server.active = ['m1', 'm2', 'solo']
  server.jobs = {
    m1: [{ agent_id: 'o1', job_id: 'jo1', agent_display_name: 'orchestrator', agent_name: 'orchestrator', status: 'working' }],
    m2: [],
    solo: [],
  }
  server.runs = [
    {
      id: 'run-1',
      project_ids: ['m1', 'm2'],
      resolved_order: ['m1', 'm2'],
      current_index: 0,
      status: 'running',
      locked: true,
      execution_mode: 'subagent',
      project_statuses: { m1: 'implementing', m2: 'pending' },
      chain_mission: '# Chain mission: Two',
    },
  ]
})

describe('FE-9777: chain member cards follow their project live', () => {
  it('a member moves Activated -> Staged -> Implementing with mode and duration, no reload', async () => {
    const wrapper = await mountBoard()

    let card = memberCard(wrapper, 'm2')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-lifecycle')).toBe('Activated')
    expect(card.find('[data-testid="jb-stat-mode"]').text()).toBe('not picked')
    expect(looseTitles(wrapper)).toEqual(['Project FE-0100'])

    serverMoves('m2', { staging_status: 'staging_complete', execution_mode: 'subagent', updated_at: '2026-10-08T11:00:00Z' })
    serverMoves('solo', { name: 'Solo renamed', updated_at: '2026-10-08T11:00:00Z' })
    server.jobs.m2 = [
      { agent_id: 'o2', job_id: 'jo2', agent_display_name: 'orchestrator', agent_name: 'orchestrator', status: 'working' },
    ]
    server.runs = [{ ...server.runs[0], current_index: 1, project_statuses: { m1: 'completed', m2: 'planning' } }]
    fire({ type: 'project:staging_complete', data: { project_id: 'm2', tenant_key: 't' } })
    fire({ type: 'project:mission_updated', data: { project_id: 'solo', tenant_key: 't' } })
    fire({ type: 'sequence:updated', data: { run_id: 'run-1', tenant_key: 't' } })
    await settle()

    expect(looseTitles(wrapper)).toEqual(['Solo renamed'])
    card = memberCard(wrapper, 'm2')
    expect(card.attributes('data-lifecycle')).toBe('Staged')
    expect(card.find('[data-testid="jb-stat-mode"]').text()).toBe('Subagent')

    const launchedAt = new Date(Date.now() - 90_000).toISOString()
    serverMoves('m2', { implementation_launched_at: launchedAt, updated_at: '2026-10-08T11:05:00Z' })
    serverMoves('solo', { name: 'Solo renamed twice', updated_at: '2026-10-08T11:05:00Z' })
    server.runs = [{ ...server.runs[0], project_statuses: { m1: 'completed', m2: 'implementing' } }]
    fire({ type: 'project:implementation_launched', data: { project_id: 'm2', tenant_key: 't' } })
    fire({ type: 'project:mission_updated', data: { project_id: 'solo', tenant_key: 't' } })
    await settle()

    expect(looseTitles(wrapper)).toEqual(['Solo renamed twice'])
    card = memberCard(wrapper, 'm2')
    expect(card.attributes('data-lifecycle')).toBe('Implementing')
    expect(card.find('[data-testid="jb-stat-duration"]').text()).toMatch(/^1m \d+s$/)
    expect(card.text()).toContain('About FE-0202')

    wrapper.unmount()
  })

  it('an older list row never overwrites a newer detail copy of the member', async () => {
    const wrapper = await mountBoard()
    const { useProjectStore } = await import('@/stores/projects')
    const projectStore = useProjectStore()

    serverMoves('m2', {
      staging_status: 'staging_complete',
      execution_mode: 'subagent',
      implementation_launched_at: '2026-10-08T11:05:00Z',
      updated_at: '2026-10-08T11:05:00Z',
    })
    await projectStore.fetchProject('m2')
    await flushPromises()

    expect(memberCard(wrapper, 'm2').attributes('data-lifecycle')).toBe('Implementing')
    wrapper.unmount()
  })
})
