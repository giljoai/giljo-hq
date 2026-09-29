import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const server = vi.hoisted(() => ({ row: null, agents: [] }))
const h = vi.hoisted(() => ({ copy: vi.fn(), toast: vi.fn() }))

vi.mock('@/services/api', () => {
  const ok = (data) => Promise.resolve({ data })
  const api = {
    projects: {
      getActive: () => ok([{ ...server.row }]),
      getOrchestrator: () => ok({ orchestrator: null }),
      launchImplementation: () => {
        server.row.implementation_launched_at = '2026-09-25T00:00:00Z'
        return ok({ success: true })
      },
      update: (id, patch) => {
        Object.assign(server.row, patch)
        return ok({ ...server.row })
      },
      unstage: () => {
        Object.assign(server.row, { staging_status: null, mission: '' })
        return ok({})
      },
      restage: () => {
        Object.assign(server.row, { staging_status: null, mission: '', implementation_launched_at: null })
        return ok({})
      },
    },
    prompts: {
      implementation: () => ok({ prompt: 'IMPL PROMPT', agent_count: 0 }),
      staging: () => {
        server.row.staging_status = 'staged'
        return ok({ prompt: 'STAGING PROMPT' })
      },
    },
    orchestrator: {
      launchProject: () => ok({ success: true }),
    },
    agentJobs: { list: () => ok({ jobs: server.agents, total: server.agents.length, limit: 50, offset: 0 }) },
    settings: { getHeadlessLaunch: () => ok({ allow_headless_launch: true }) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: h.copy }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.toast }) }))

import JobsViewportView from './JobsViewportView.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

let pinia
async function mountBoard() {
  const wrapper = mount(JobsViewportView, {
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
  await flushPromises()
  return wrapper
}

const stageBtn = (w) => w.find('[data-testid="jbf-stage"]')
const footerState = (w) => w.find('[data-testid="jb-footer"]').attributes('data-footer-state')

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  window.localStorage.getItem.mockImplementation((k) => (k === 'jobs.density.v2' ? 'detailed' : null))
  h.copy.mockResolvedValue(true)
  server.row = {
    id: 'p-1',
    taxonomy_alias: 'FE-0301',
    name: 'Board round trip',
    status: 'active',
    staging_status: null,
    execution_mode: null,
    mission: '',
    implementation_launched_at: null,
  }
  server.agents = []
})

describe('Jobs board: card actions show their new state without a reload', () => {
  it('Stage: the card shows Unstage after the board re-reads the project', async () => {
    const wrapper = await mountBoard()
    await wrapper.find('[data-testid="radio-multi-terminal"]').trigger('click')
    await flushPromises()
    await stageBtn(wrapper).trigger('click')
    await flushPromises()
    expect(stageBtn(wrapper).text()).toBe('Unstage')
  })

  it('Unstage: the card goes back to Stage', async () => {
    server.row = { ...server.row, staging_status: 'staged', execution_mode: 'multi_terminal' }
    const wrapper = await mountBoard()
    expect(stageBtn(wrapper).text()).toBe('Unstage')
    await stageBtn(wrapper).trigger('click')
    await flushPromises()
    expect(stageBtn(wrapper).text()).toBe('Stage')
  })

  it('Re-Stage: a staged card returns to ready', async () => {
    server.row = { ...server.row, staging_status: 'staging_complete', execution_mode: 'subagent', mission: 'M' }
    const wrapper = await mountBoard()
    expect(footerState(wrapper)).toBe('staged')
    await stageBtn(wrapper).trigger('click')
    await flushPromises()
    expect(footerState(wrapper)).toBe('ready')
    expect(stageBtn(wrapper).text()).toBe('Stage')
  })

  it('Implement: a staged card becomes implementing and its rows go live', async () => {
    server.row = { ...server.row, staging_status: 'staging_complete', execution_mode: 'multi_terminal', mission: 'M' }
    server.agents = [
      { agent_id: 'a-or', job_id: 'j-or', agent_display_name: 'orchestrator', agent_name: 'orchestrator', status: 'waiting', project_id: 'p-1' },
    ]
    const wrapper = await mountBoard()
    await wrapper.find('[data-testid="jbf-implement"]').trigger('click')
    await flushPromises()
    expect(footerState(wrapper)).toBe('implementing')
    expect(h.copy).toHaveBeenCalledWith('IMPL PROMPT')
    expect(wrapper.find('[data-testid="jb-agent-recopy"]').exists()).toBe(true)
  })

  it('Implement from another tab (project:launched) moves this card too', async () => {
    server.row = { ...server.row, staging_status: 'staging_complete', execution_mode: 'multi_terminal', mission: 'M' }
    const wrapper = await mountBoard()
    const { useProjectStateStore } = await import('@/stores/projectStateStore')
    useProjectStateStore().setLaunched('p-1', true)
    await flushPromises()
    expect(footerState(wrapper)).toBe('implementing')
  })
})
