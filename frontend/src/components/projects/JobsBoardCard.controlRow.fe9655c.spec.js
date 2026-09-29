import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({
  agentPrompt: vi.fn(),
  getOrchestrator: vi.fn(),
  copy: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    prompts: { agentPrompt: (...a) => h.agentPrompt(...a) },
    projects: { getOrchestrator: (...a) => h.getOrchestrator(...a) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: h.copy }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.toast }) }))

import JobsBoardCard from './JobsBoardCard.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}
const menuStub = {
  template: `<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>`,
}

const LAUNCHED = {
  id: 'p-run',
  taxonomy_alias: 'FE-0200',
  name: 'Running project',
  status: 'active',
  staging_status: 'staging_complete',
  implementation_launched_at: '2026-09-24T20:00:00Z',
  execution_mode: 'multi_terminal',
  mission: 'Do the work',
}
const IMPLEMENTER = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'waiting', project_id: 'p-run' }

let pinia
function mountCard(project, agents) {
  return mount(JobsBoardCard, {
    props: { project, agents, now: Date.parse('2026-09-24T20:10:00Z') },
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub, 'v-menu': menuStub } },
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  h.agentPrompt.mockResolvedValue({ data: { prompt: 'IMPLEMENTER PROMPT' } })
  h.getOrchestrator.mockResolvedValue({ data: { orchestrator: null } })
  h.copy.mockResolvedValue(true)
})

describe('JobsBoardCard control row (FE-9655c)', () => {
  it('before launch the crew is display-only (the pane lists it, no live controls)', async () => {
    const staged = { ...LAUNCHED, implementation_launched_at: null }
    const wrapper = mountCard(staged, [IMPLEMENTER])
    await flushPromises()
    expect(wrapper.find('[data-testid="jb-agent-row"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-agent-play"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-agent-kebab"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-footer"]').attributes('data-footer-state')).toBe('staged')
  })

  it('play copies the agent prompt, fades once the agent is working, and replay copies again', async () => {
    const wrapper = mountCard(LAUNCHED, [IMPLEMENTER])
    await flushPromises()

    await wrapper.find('[data-testid="jb-agent-play"]').trigger('click')
    await flushPromises()
    expect(h.agentPrompt).toHaveBeenCalledWith('a-im')
    expect(h.copy).toHaveBeenCalledWith('IMPLEMENTER PROMPT')

    await wrapper.setProps({ agents: [{ ...IMPLEMENTER, status: 'working' }] })
    expect(wrapper.find('[data-testid="jb-agent-play"]').exists()).toBe(false)
    await wrapper.find('[data-testid="jb-agent-recopy"]').trigger('click')
    await flushPromises()
    expect(h.copy).toHaveBeenCalledTimes(2)
  })

  it('kebab actions reach the board with the agent (and the project for messages)', async () => {
    const wrapper = mountCard(LAUNCHED, [IMPLEMENTER])
    await flushPromises()
    await wrapper.find('[data-testid="jb-agent-menu-job"]').trigger('click')
    await wrapper.find('[data-testid="jb-agent-menu-role"]').trigger('click')
    await wrapper.find('[data-testid="jb-agent-messages-btn"]').trigger('click')
    expect(wrapper.emitted('agent-job')[0][0].job_id).toBe('j-im')
    expect(wrapper.emitted('agent-role')[0][0].job_id).toBe('j-im')
    const [agent, project] = wrapper.emitted('agent-messages')[0]
    expect(agent.job_id).toBe('j-im')
    expect(project.id).toBe('p-run')
  })

  it('parallel projects: each card has its own independent row', async () => {
    const a = mountCard(LAUNCHED, [IMPLEMENTER])
    const b = mountCard({ ...LAUNCHED, id: 'p-other' }, [{ ...IMPLEMENTER, job_id: 'j-other', agent_id: 'a-other', project_id: 'p-other' }])
    await flushPromises()
    await a.find('[data-testid="jb-agent-play"]').trigger('click')
    await flushPromises()
    await a.setProps({ agents: [{ ...IMPLEMENTER, status: 'working' }] })
    expect(a.find('[data-testid="jb-agent-recopy"]').exists()).toBe(true)
    expect(b.find('[data-testid="jb-agent-play"]').exists()).toBe(true)
  })
})
