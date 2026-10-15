import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({
  launchImplementation: vi.fn(),
  chainMember: vi.fn(),
  getOrchestrator: vi.fn(),
  copy: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    prompts: { chainMember: (...a) => h.chainMember(...a) },
    projects: {
      launchImplementation: (...a) => h.launchImplementation(...a),
      getOrchestrator: (...a) => h.getOrchestrator(...a),
    },
    settings: { getExecutionModeDefault: () => Promise.resolve({ data: { execution_mode_default: 'ask' } }) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: h.copy }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.toast }) }))

import JobsBoardCard from './JobsBoardCard.vue'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})

const tooltipStub = { template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>` }
const menuStub = { template: `<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>` }

const ORDER = ['p-1', 'p-2', 'p-3']
const CHAIN_CTX = {
  runId: 'run-9761',
  locked: true,
  projects: [],
  missingIds: [],
  tabs: ORDER.map((projectId, order) => ({ projectId, order, name: `Step ${order + 1}` })),
}

function member(id, overrides = {}) {
  return {
    id,
    name: `Member ${id}`,
    status: 'inactive',
    staging_status: 'staged',
    implementation_launched_at: null,
    execution_mode: 'claude_code_cli',
    mission: '',
    ...overrides,
  }
}

function orchestrator(projectId) {
  return { agent_id: `a-${projectId}`, job_id: `j-${projectId}`, agent_display_name: 'orchestrator', status: 'waiting', project_id: projectId }
}

function seedRun(overrides = {}) {
  useSequenceRunStore()._testSeedRuns([
    {
      id: 'run-9761',
      project_ids: ORDER,
      resolved_order: ORDER,
      current_index: 0,
      status: 'running',
      execution_mode: 'claude_code_cli',
      locked: true,
      project_statuses: { 'p-1': 'completed', 'p-2': 'pending', 'p-3': 'pending' },
      ...overrides,
    },
  ])
}

let pinia
function mountMember(project, agents = [orchestrator(project.id)]) {
  return mount(JobsBoardCard, {
    props: { project, agents, now: Date.parse('2026-10-08T20:00:00Z'), chainCtx: CHAIN_CTX, showStaging: false },
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub, 'v-menu': menuStub } },
  })
}

const copyPrompt = (wrapper) => wrapper.find('[data-testid="sca-copy-prompt"]')
const rowPlay = (wrapper) => wrapper.find('[data-testid="jb-agent-play"]')

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  h.launchImplementation.mockResolvedValue({ data: { success: true } })
  h.chainMember.mockResolvedValue({ data: { prompt: 'MEMBER 2 PROMPT' } })
  h.getOrchestrator.mockResolvedValue({ data: { orchestrator: null } })
  h.copy.mockResolvedValue(true)
})

describe('JobsBoardCard: the next chain member starts once its predecessor closes out (BE-9761a, FE-9749)', () => {
  it('the member the closeout opened waits for pickup: one filled Copy prompt that copies that member prompt', async () => {
    seedRun({ current_index: 1 })
    const wrapper = mountMember(member('p-2', { status: 'active', implementation_launched_at: '2026-10-08T19:59:00Z' }))
    await flushPromises()

    expect(wrapper.find('[data-testid="sca-pickup-hint"]').text()).toBe('No agent has picked this up yet')
    expect(copyPrompt(wrapper).classes()).toContain('jb-btn-primary')
    expect(rowPlay(wrapper).exists()).toBe(false)
    await copyPrompt(wrapper).trigger('click')
    await flushPromises()
    expect(h.launchImplementation).toHaveBeenCalledWith('p-2')
    expect(h.chainMember).toHaveBeenCalledWith('p-2')
    expect(h.launchImplementation.mock.invocationCallOrder[0]).toBeLessThan(h.chainMember.mock.invocationCallOrder[0])
    expect(h.copy).toHaveBeenCalledWith('MEMBER 2 PROMPT')
  })

  it('a run mid-chain before the server opened gates still offers the start, which opens the gate', async () => {
    seedRun({ current_index: 0 })
    const wrapper = mountMember(member('p-2'))
    await flushPromises()

    await copyPrompt(wrapper).trigger('click')
    await flushPromises()
    expect(h.launchImplementation).toHaveBeenCalledWith('p-2')
    expect(h.copy).toHaveBeenCalledWith('MEMBER 2 PROMPT')
  })

  it('a refused gate copies nothing', async () => {
    seedRun({ current_index: 1 })
    h.launchImplementation.mockRejectedValue({ response: { status: 409, data: { detail: 'not your turn' } } })
    const wrapper = mountMember(member('p-2'))
    await flushPromises()
    await copyPrompt(wrapper).trigger('click')
    await flushPromises()
    expect(h.chainMember).not.toHaveBeenCalled()
    expect(h.copy).not.toHaveBeenCalled()
  })

  it('once its orchestrator picks up, the current member goes compact: no Copy prompt', async () => {
    seedRun({ current_index: 1 })
    const working = { ...orchestrator('p-2'), status: 'working' }
    const wrapper = mountMember(member('p-2', { status: 'active', implementation_launched_at: '2026-10-08T19:59:00Z' }), [working])
    await flushPromises()
    expect(copyPrompt(wrapper).exists()).toBe(false)
    expect(wrapper.find('[data-testid="staging-control-area"]').exists()).toBe(false)
    expect(rowPlay(wrapper).exists()).toBe(false)
  })

  it('a member whose predecessor is still open offers no start button', async () => {
    seedRun({ current_index: 0 })
    const wrapper = mountMember(member('p-3'))
    await flushPromises()
    expect(copyPrompt(wrapper).exists()).toBe(false)
    expect(rowPlay(wrapper).exists()).toBe(false)
  })

  it('a finished member offers no start button', async () => {
    seedRun({ current_index: 1 })
    const done = { ...orchestrator('p-1'), status: 'complete' }
    const wrapper = mountMember(
      member('p-1', { status: 'completed', staging_status: 'staging_complete', implementation_launched_at: '2026-10-08T18:00:00Z' }),
      [done],
    )
    await flushPromises()
    expect(copyPrompt(wrapper).exists()).toBe(false)
    expect(rowPlay(wrapper).exists()).toBe(false)
  })

  it('the head offers no start of its own before Implement Chain releases the chain', async () => {
    seedRun({ status: 'pending', project_statuses: { 'p-1': 'pending', 'p-2': 'pending', 'p-3': 'pending' } })
    const wrapper = mountMember(member('p-1'))
    await flushPromises()
    expect(copyPrompt(wrapper).exists()).toBe(false)
    expect(rowPlay(wrapper).exists()).toBe(false)
  })
})
