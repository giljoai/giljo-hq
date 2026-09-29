import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsBoardDetailModal from './JobsBoardDetailModal.vue'

const vuetify = createVuetify()
const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', name: 'Root', component: { template: '<div />' } }],
})

const project = { id: 'p-1', taxonomy_alias: 'BE-6177', name: 'Archive refuses without a closeout entry', execution_mode: 'multi_terminal' }
const orch = { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'closed', steps: { completed: 5, total: 5 } }
const impl = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'complete', phase: 1, steps: { completed: 6, total: 6 } }

const stubs = {
  MessageComposer: {
    props: ['projectId', 'orchestratorAgentId', 'chainMode', 'conductorAgentId', 'chainRunId'],
    template: '<div data-testid="composer-stub">{{ projectId }}|{{ orchestratorAgentId }}|{{ chainMode }}|{{ conductorAgentId }}|{{ chainRunId }}</div>',
  },
  ProjectStatusBanner: {
    props: ['showCloseoutButton', 'projectDoneStatus'],
    emits: ['open-closeout-modal'],
    template: '<div data-testid="banner-stub" @click="$emit(\'open-closeout-modal\')">{{ showCloseoutButton }}</div>',
  },
  'v-dialog': { template: '<div><slot /></div>' },
}

function mountModal(props = {}) {
  return mount(JobsBoardDetailModal, {
    props: { modelValue: true, project, agents: [orch, impl], now: Date.now(), ...props },
    global: { plugins: [vuetify, router], stubs },
  })
}

describe('JobsBoardDetailModal hosts the Implementation tab\'s surround (FE-9681)', () => {
  it('renders the composer addressed at this project\'s orchestrator', () => {
    const wrapper = mountModal()
    expect(wrapper.find('[data-testid="composer-stub"]').text()).toBe('p-1|a-or|false||')
  })

  it('a chain member\'s composer reroutes to the conductor', () => {
    const wrapper = mountModal({ chainCtx: { runId: 'run-1', conductor: { agentId: 'cond-1' } } })
    expect(wrapper.find('[data-testid="composer-stub"]').text()).toBe('p-1|a-or|true|cond-1|run-1')
  })

  it('shows the proposed execution order for a multi-terminal project, not for subagent', () => {
    expect(mountModal().find('[data-testid="execution-order-bar"]').exists()).toBe(true)
    expect(mountModal({ project: { ...project, execution_mode: 'subagent' } }).find('[data-testid="execution-order-bar"]').exists()).toBe(false)
  })

  it('renders the status banner from the board\'s closeout state and relays its asks', async () => {
    const wrapper = mountModal({ banner: { showCloseoutButton: true, projectDoneStatus: null } })
    expect(wrapper.find('[data-testid="banner-stub"]').text()).toBe('true')
    await wrapper.find('[data-testid="banner-stub"]').trigger('click')
    expect(wrapper.emitted('open-closeout')).toHaveLength(1)
  })

  it('the review strip opens the closeout on the board instead of a route', async () => {
    const wrapper = mountModal()
    const btn = wrapper.find('[data-testid="jb-review-strip-btn"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('href')).toBeUndefined()
    await btn.trigger('click')
    expect(wrapper.emitted('open-closeout')).toHaveLength(1)
  })

  it('source carries no ProjectLaunch route name (the page is retired)', async () => {
    const source = (await import('./JobsBoardDetailModal.vue?raw')).default
    expect(source).not.toMatch(/ProjectLaunch/)
  })
})
