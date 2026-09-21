
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsTab from '@/components/projects/JobsTab.vue'
import api from '@/services/api'
import { useAgentJobsStore } from '@/stores/agentJobsStore'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useProjectStore } from '@/stores/projects'
import { useUserStore } from '@/stores/user'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

const vuetify = createVuetify()

const hubRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})



const tooltipStub = {
  props: ['text'],
  template: `<div class="v-tooltip" :data-tooltip-text="text"><slot name="activator" :props="{}" /></div>`,
}

const listItemStub = {
  props: ['title', 'prependIcon'],
  template: `<div class="v-list-item" v-bind="$attrs" :title="title"><slot /></div>`,
}

const menuStub = {
  template: `<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>`,
}

const stubs = {
  'v-tooltip': tooltipStub,
  'v-menu': menuStub,
  'v-list-item': listItemStub,
  AgentDetailsModal: true,
  AgentJobModal: true,
  HandoverModal: true,
  MessageComposer: true,
  ExecutionOrderBar: true,
}


const mockProject = {
  project_id: 'proj-fe5058',
  id: 'proj-fe5058',
  name: 'FE-5058 Test Project',
  execution_mode: 'multi_terminal',
}

function makeAgent(overrides = {}) {
  return {
    job_id: 'job-001',
    agent_id: 'agent-001',
    agent_name: 'orchestrator',
    agent_display_name: 'orchestrator',
    status: 'working',
    phase: null,
    project_id: 'proj-fe5058',
    messages_sent_count: 0,
    messages_waiting_count: 0,
    messages_read_count: 0,
    ...overrides,
  }
}


async function mountWithAgent(agentOverrides = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)

  const userStore = useUserStore()
  userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }

  const wrapper = mount(JobsTab, {
    props: { project: mockProject },
    global: {
      plugins: [pinia, vuetify, hubRouter],
      stubs,
    },
  })

  await wrapper.vm.$nextTick()

  const agentJobsStore = useAgentJobsStore()
  agentJobsStore.setJobs([makeAgent(agentOverrides)])
  await wrapper.vm.$nextTick()

  return wrapper
}


describe('JobsTab.vue — orchestrator-button visibility', () => {
  beforeEach(() => {
    // vi.clearAllMocks() already called by tests/setup.js beforeEach
  })

  it('shows both buttons for orchestrator with status=working (inline + menu)', async () => {
    const wrapper = await mountWithAgent({ status: 'working' })

    const inlineHandover = wrapper.find('.actions-inline [aria-label="Hand over session"]')
    const inlineStop = wrapper.find('.actions-inline [aria-label="Stop project"]')
    expect(inlineHandover.exists(), 'inline hand-over button').toBe(true)
    expect(inlineStop.exists(), 'inline stop button').toBe(true)

    const menuHandover = wrapper.find('.actions-menu [title="Hand over"]')
    const menuStop = wrapper.find('.actions-menu [title="Stop project"]')
    expect(menuHandover.exists(), 'menu hand-over item').toBe(true)
    expect(menuStop.exists(), 'menu stop item').toBe(true)
  })

  it('hides both buttons for non-orchestrator agent_display_name', async () => {
    const wrapper = await mountWithAgent({
      agent_name: 'implementer',
      agent_display_name: 'implementer',
      status: 'working',
    })

    expect(wrapper.find('.actions-inline [aria-label="Hand over session"]').exists()).toBe(false)
    expect(wrapper.find('.actions-inline [aria-label="Stop project"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Hand over"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Stop project"]').exists()).toBe(false)
  })

  it('hides stop button but keeps hand-over when status=complete', async () => {
    const wrapper = await mountWithAgent({ status: 'complete' })

    expect(wrapper.find('.actions-inline [aria-label="Hand over session"]').exists()).toBe(true)
    expect(wrapper.find('.actions-inline [aria-label="Stop project"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Hand over"]').exists()).toBe(true)
    expect(wrapper.find('.actions-menu [title="Stop project"]').exists()).toBe(false)
  })

  it('hides hand-over button for decommissioned status', async () => {
    const wrapper = await mountWithAgent({ status: 'decommissioned' })

    expect(wrapper.find('.actions-inline [aria-label="Hand over session"]').exists()).toBe(false)
    expect(wrapper.find('.actions-inline [aria-label="Stop project"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Hand over"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Stop project"]').exists()).toBe(false)
  })

  it('hides hand-over button for handed_over status', async () => {
    const wrapper = await mountWithAgent({ status: 'handed_over' })

    expect(wrapper.find('.actions-inline [aria-label="Hand over session"]').exists()).toBe(false)
    expect(wrapper.find('.actions-inline [aria-label="Stop project"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Hand over"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Stop project"]').exists()).toBe(false)
  })

  it('hides hand-over button for waiting status', async () => {
    const wrapper = await mountWithAgent({ status: 'waiting' })

    expect(wrapper.find('.actions-inline [aria-label="Hand over session"]').exists()).toBe(false)
    expect(wrapper.find('.actions-inline [aria-label="Stop project"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Hand over"]').exists()).toBe(false)
    expect(wrapper.find('.actions-menu [title="Stop project"]').exists()).toBe(false)
  })
})


describe('JobsTab.vue — FE-6019 execution_mode store-first', () => {
  async function mountWithMode({ propMode, storeMode } = {}) {
    const pinia = createPinia()
    setActivePinia(pinia)

    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }

    const projectId = 'proj-fe6019'
    const projectProp = {
      project_id: projectId,
      id: projectId,
      name: 'FE-6019 Test Project',
      execution_mode: propMode,
    }

    const wrapper = mount(JobsTab, {
      props: { project: projectProp },
      global: {
        plugins: [pinia, vuetify, hubRouter],
        stubs,
      },
    })

    await wrapper.vm.$nextTick()

    const projectStateStore = useProjectStateStore()
    projectStateStore.setProject({
      id: projectId,
      project_id: projectId,
      execution_mode: storeMode,
      staging_status: 'staging_complete',
    })

    const agentJobsStore = useAgentJobsStore()
    agentJobsStore.setJobs([
      {
        job_id: 'job-orch',
        agent_id: 'agent-orch',
        agent_name: 'orchestrator',
        agent_display_name: 'orchestrator',
        status: 'working',
        phase: null,
        project_id: projectId,
        messages_sent_count: 0,
        messages_waiting_count: 0,
        messages_read_count: 0,
      },
      {
        job_id: 'job-spec',
        agent_id: 'agent-spec',
        agent_name: 'implementer',
        agent_display_name: 'implementer',
        status: 'waiting',
        phase: 1,
        project_id: projectId,
        messages_sent_count: 0,
        messages_waiting_count: 0,
        messages_read_count: 0,
      },
    ])

    await wrapper.vm.$nextTick()
    return wrapper
  }

  it('[FE-6019] isSubagentMode is false when store has multi_terminal even if prop is stale CLI', async () => {
    const wrapper = await mountWithMode({ propMode: 'claude_code_cli', storeMode: 'multi_terminal' })

    const phaseBadges = wrapper.findAll('[data-testid="phase-badge"]')
    const allBadge = phaseBadges.find(b => b.text() === 'All')
    expect(allBadge, 'phase badge should not be "All" in multi_terminal mode').toBeUndefined()
  })

  it('[FE-6019] isSubagentMode is true when store has CLI mode', async () => {
    const wrapper = await mountWithMode({ propMode: 'claude_code_cli', storeMode: 'claude_code_cli' })

    const phaseBadges = wrapper.findAll('[data-testid="phase-badge"]')
    const allBadge = phaseBadges.find(b => b.text() === 'All')
    expect(allBadge, 'phase badge should be "All" in CLI (subagent) mode').toBeDefined()
  })

  it('[BE-9035a] isSubagentMode is true when store has generic_mcp (was misclassified as multi-terminal)', async () => {
    const wrapper = await mountWithMode({ propMode: 'generic_mcp', storeMode: 'generic_mcp' })

    const phaseBadges = wrapper.findAll('[data-testid="phase-badge"]')
    const allBadge = phaseBadges.find(b => b.text() === 'All')
    expect(allBadge, 'phase badge should be "All" in generic_mcp (subagent) mode').toBeDefined()
  })
})


describe('JobsTab.vue — FE-9122 execution_mode stays fresh via projectStore.updateProject', () => {
  it('re-pick (updateProject resolves subagent) flips the subagent panel with no direct store write', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }

    const projectId = 'proj-fe9122'
    const wrapper = mount(JobsTab, {
      props: {
        project: { project_id: projectId, id: projectId, name: 'FE-9122 Test Project', execution_mode: 'multi_terminal' },
      },
      global: { plugins: [pinia, vuetify, hubRouter], stubs },
    })
    await wrapper.vm.$nextTick()

    const projectStateStore = useProjectStateStore()
    projectStateStore.setProject({
      id: projectId,
      project_id: projectId,
      execution_mode: 'multi_terminal',
      staging_status: 'staging_complete',
    })

    const agentJobsStore = useAgentJobsStore()
    agentJobsStore.setJobs([
      {
        job_id: 'job-spec-9122',
        agent_id: 'agent-spec-9122',
        agent_name: 'implementer',
        agent_display_name: 'implementer',
        status: 'waiting',
        phase: 1,
        project_id: projectId,
        messages_sent_count: 0,
        messages_waiting_count: 0,
        messages_read_count: 0,
      },
    ])
    await wrapper.vm.$nextTick()

    let phaseBadges = wrapper.findAll('[data-testid="phase-badge"]')
    expect(phaseBadges.find((b) => b.text() === 'All'), 'no All badge in multi_terminal mode').toBeUndefined()

    api.projects.update.mockResolvedValueOnce({
      data: { id: projectId, project_id: projectId, execution_mode: 'subagent', staging_status: 'staging_complete' },
    })
    const projectStore = useProjectStore()
    await projectStore.updateProject(projectId, { execution_mode: 'subagent' })
    await wrapper.vm.$nextTick()

    phaseBadges = wrapper.findAll('[data-testid="phase-badge"]')
    expect(phaseBadges.find((b) => b.text() === 'All'), 'All badge appears once bridged to subagent mode').toBeDefined()
  })
})


describe('JobsTab.vue — BE-6200 chain conductor excluded from project lane', () => {
  async function mountWithJobs(jobs) {
    const pinia = createPinia()
    setActivePinia(pinia)
    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }

    const wrapper = mount(JobsTab, {
      props: { project: mockProject },
      global: { plugins: [pinia, vuetify, hubRouter], stubs },
    })
    await wrapper.vm.$nextTick()

    const agentJobsStore = useAgentJobsStore()
    agentJobsStore.setJobs(jobs)
    await wrapper.vm.$nextTick()
    return wrapper
  }

  it('excludes a conductor whose execution carries a real project_id (the real leak shape)', async () => {
    const wrapper = await mountWithJobs([
      makeAgent({
        job_id: 'job-impl',
        agent_id: 'agent-impl',
        agent_name: 'implementer',
        agent_display_name: 'implementer',
        status: 'working',
        project_id: 'proj-fe5058',
        chain_conductor: false,
      }),
      makeAgent({
        job_id: 'job-conductor',
        agent_id: 'agent-conductor',
        agent_name: 'conductor',
        agent_display_name: 'conductor',
        status: 'working',
        project_id: 'proj-fe5058',
        chain_conductor: true,
      }),
    ])

    const rows = wrapper.findAll('[data-testid="agent-row"]')
    const names = rows.map((r) => r.text())
    expect(rows.length, 'only the project agent renders').toBe(1)
    expect(names.some((t) => t.includes('conductor')), 'conductor must not render').toBe(false)
    expect(names.some((t) => t.includes('implementer')), 'project agent renders').toBe(true)
  })

  it('renders all rows when none are conductors (solo path unaffected)', async () => {
    const wrapper = await mountWithJobs([
      makeAgent({ job_id: 'j1', agent_id: 'a1', agent_display_name: 'orchestrator', status: 'working' }),
      makeAgent({ job_id: 'j2', agent_id: 'a2', agent_display_name: 'implementer', status: 'waiting', phase: 1 }),
    ])
    expect(wrapper.findAll('[data-testid="agent-row"]').length).toBe(2)
  })
})


describe('JobsTab.vue — BE-6229 conductor excluded on the live WS store path', () => {
  async function mountSeeded(jobs) {
    const pinia = createPinia()
    setActivePinia(pinia)
    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }

    const wrapper = mount(JobsTab, {
      props: { project: mockProject },
      global: { plugins: [pinia, vuetify, hubRouter], stubs },
    })
    await wrapper.vm.$nextTick()

    const agentJobsStore = useAgentJobsStore()
    agentJobsStore.setJobs(jobs)
    await wrapper.vm.$nextTick()
    return { wrapper, agentJobsStore }
  }

  it('excludes a conductor row upserted via WS (chain_conductor flag, NO setJobs reload)', async () => {
    const { wrapper, agentJobsStore } = await mountSeeded([
      makeAgent({
        job_id: 'job-impl',
        agent_id: 'agent-impl',
        agent_display_name: 'implementer',
        status: 'working',
      }),
    ])

    agentJobsStore.upsertJob({
      job_id: 'job-conductor',
      agent_id: 'agent-conductor',
      agent_display_name: 'conductor',
      status: 'working',
      project_id: mockProject.project_id,
      chain_conductor: true,
    })
    await wrapper.vm.$nextTick()

    const rows = wrapper.findAll('[data-testid="agent-row"]')
    expect(rows.length, 'only the project agent renders').toBe(1)
    expect(rows.map((r) => r.text()).some((t) => t.includes('conductor'))).toBe(false)
  })

  it('excludes a project-less/foreign row upserted via WS even without the flag (belt)', async () => {
    const { wrapper, agentJobsStore } = await mountSeeded([
      makeAgent({
        job_id: 'job-impl',
        agent_id: 'agent-impl',
        agent_display_name: 'implementer',
        status: 'working',
      }),
    ])

    agentJobsStore.upsertJob({
      job_id: 'job-conductor-noflag',
      agent_id: 'agent-conductor-noflag',
      agent_display_name: 'conductor',
      status: 'working',
      project_id: null,
    })
    agentJobsStore.upsertJob({
      job_id: 'job-foreign',
      agent_id: 'agent-foreign',
      agent_display_name: 'implementer',
      status: 'working',
      project_id: 'some-other-project',
    })
    await wrapper.vm.$nextTick()

    const rows = wrapper.findAll('[data-testid="agent-row"]')
    expect(rows.length, 'only the open project agent renders').toBe(1)
    expect(rows.map((r) => r.text()).some((t) => t.includes('conductor'))).toBe(false)
  })
})



describe('JobsTab.vue — chain member play button (FE-9629)', () => {
  const MEMBER_PID = 'proj-fe5058'

  function seedChainRun(currentIndex, statuses) {
    const sequenceRunStore = useSequenceRunStore()
    sequenceRunStore._testSeedRuns([
      {
        id: 'run-1',
        project_ids: [MEMBER_PID, 'p2'],
        resolved_order: [MEMBER_PID, 'p2'],
        current_index: currentIndex,
        status: 'running',
        execution_mode: 'multi_terminal',
        project_statuses: statuses,
      },
    ])
  }

  const chainCtx = {
    runId: 'run-1',
    run: {
      id: 'run-1',
      project_ids: [MEMBER_PID, 'p2'],
      resolved_order: [MEMBER_PID, 'p2'],
      current_index: 0,
      project_statuses: { [MEMBER_PID]: 'planning', p2: 'pending' },
    },
    tabs: [
      { projectId: MEMBER_PID, taxonomyAlias: 'FE-9640', name: 'Ingest rewrite' },
      { projectId: 'p2', taxonomyAlias: 'FE-9641', name: 'Search index' },
    ],
  }

  async function mountChainMember(projectId, currentIndex, statuses) {
    const pinia = createPinia()
    setActivePinia(pinia)
    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }
    seedChainRun(currentIndex, statuses)

    const wrapper = mount(JobsTab, {
      props: {
        project: { ...mockProject, project_id: projectId, id: projectId },
        chainCtx: { ...chainCtx, run: { ...chainCtx.run, current_index: currentIndex, project_statuses: statuses } },
      },
      global: { plugins: [pinia, vuetify, hubRouter], stubs },
    })
    await wrapper.vm.$nextTick()
    const agentJobsStore = useAgentJobsStore()
    agentJobsStore.setJobs([
      makeAgent({ status: 'waiting', agent_display_name: 'orchestrator', project_id: projectId }),
    ])
    await wrapper.vm.$nextTick()
    return wrapper
  }

  it('shows the play button for the member at the current index, though staging is not complete', async () => {
    const wrapper = await mountChainMember(MEMBER_PID, 0, { [MEMBER_PID]: 'planning', p2: 'pending' })

    const btn = wrapper.find('.play-cell [aria-label="Copy agent prompt"]')
    expect(btn.exists(), 'member play button').toBe(true)
    expect(btn.classes()).not.toContain('play-btn-faded')
    expect(wrapper.find('.play-cell .v-tooltip').attributes('data-tooltip-text')).toBe('Copy prompt')
  })

  it('renders the waiting member faded, naming what it waits for, in the real row', async () => {
    const wrapper = await mountChainMember('p2', 0, { [MEMBER_PID]: 'planning', p2: 'pending' })

    const btn = wrapper.find('.play-cell [aria-label="Copy agent prompt"]')
    expect(btn.exists(), 'faded member play button').toBe(true)
    expect(btn.classes()).toContain('play-btn-faded')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(wrapper.find('.play-cell .v-tooltip').attributes('data-tooltip-text')).toBe(
      'Starts after FE-9640 closes out',
    )
  })

  it('leaves a SOLO project on the staging gate (no chain context, no play button)', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }

    const wrapper = mount(JobsTab, {
      props: { project: mockProject },
      global: { plugins: [pinia, vuetify, hubRouter], stubs },
    })
    await wrapper.vm.$nextTick()
    useAgentJobsStore().setJobs([makeAgent({ status: 'waiting', agent_display_name: 'orchestrator' })])
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.play-cell [aria-label="Copy agent prompt"]').exists()).toBe(false)
  })
})
