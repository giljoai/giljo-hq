/**
 * JobsTab.spec.js — FE-5058
 *
 * Regression tests: orchestrator-only button visibility in both layout sections
 * (.actions-inline and .actions-menu) for the Hand over and Stop project actions.
 *
 * Edition scope: CE
 */

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

const vuetify = createVuetify()

// FE-9427: JobsTab reaches useRouter() through useJobActions (openAgentThread
// pushes the named 'Hub' route). Mounted without a router that returned
// `undefined`, so the deep-link path was inert.
const hubRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})

// tests/setup.js already mocks @/services/api and @/composables/useToast
// globally — no duplication needed.

// ---------------------------------------------------------------------------
// Stubs
// ---------------------------------------------------------------------------

/**
 * Override v-tooltip to expose the #activator slot so the buttons inside it
 * are actually rendered in jsdom. The global stub in tests/setup.js only
 * renders the default slot, which hides activator-slotted buttons.
 */
const tooltipStub = {
  props: ['text'],
  template: `<div class="v-tooltip" :data-tooltip-text="text"><slot name="activator" :props="{}" /></div>`,
}

/**
 * Override v-list-item to forward the title prop as an HTML attribute so
 * tests can query [title="Hand over"] etc. The global stub does not do this.
 */
const listItemStub = {
  props: ['title', 'prependIcon'],
  template: `<div class="v-list-item" v-bind="$attrs" :title="title"><slot /></div>`,
}

/**
 * Override v-menu to render both the #activator slot AND the default slot
 * (the list content). The global stub only renders the default slot, which
 * is correct for the list — but we add activator too so the wrapper renders
 * fully without console errors.
 */
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

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

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
    // BE-6229: real agent rows always carry the project they belong to; the
    // JobsTab project_id guard drops null/foreign rows, so fixtures must match.
    project_id: 'proj-fe5058',
    messages_sent_count: 0,
    messages_waiting_count: 0,
    messages_read_count: 0,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Mount helper — seeds store AFTER mount (matches 0829 pattern) to avoid the
// loadJobs watcher overwriting the store with the globally-mocked empty list.
// ---------------------------------------------------------------------------

async function mountWithAgent(agentOverrides = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)

  // Minimal user context required by some store guards
  const userStore = useUserStore()
  userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }

  const wrapper = mount(JobsTab, {
    props: { project: mockProject },
    global: {
      plugins: [pinia, vuetify, hubRouter],
      stubs,
    },
  })

  // Wait for the immediate loadJobs watch to resolve (mocked api returns [])
  await wrapper.vm.$nextTick()

  // Seed the store directly — this is authoritative for sortedJobs
  const agentJobsStore = useAgentJobsStore()
  agentJobsStore.setJobs([makeAgent(agentOverrides)])
  await wrapper.vm.$nextTick()

  return wrapper
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('JobsTab.vue — orchestrator-button visibility', () => {
  beforeEach(() => {
    // vi.clearAllMocks() already called by tests/setup.js beforeEach
  })

  it('shows both buttons for orchestrator with status=working (inline + menu)', async () => {
    const wrapper = await mountWithAgent({ status: 'working' })

    // .actions-inline — buttons are inside v-tooltip activator slots
    const inlineHandover = wrapper.find('.actions-inline [aria-label="Hand over session"]')
    const inlineStop = wrapper.find('.actions-inline [aria-label="Stop project"]')
    expect(inlineHandover.exists(), 'inline hand-over button').toBe(true)
    expect(inlineStop.exists(), 'inline stop button').toBe(true)

    // .actions-menu — list items carry title attribute via listItemStub
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
    // status=complete is NOT in the hand-over exclusion list and NOT 'working',
    // so hand-over should render but stop should not.
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

// ---------------------------------------------------------------------------
// FE-6019 regression: isSubagentMode reads store-first, not stale prop
// ---------------------------------------------------------------------------

describe('JobsTab.vue — FE-6019 execution_mode store-first', () => {
  /**
   * Mount helper for FE-6019 tests: accepts explicit project prop overrides and
   * allows seeding the projectStateStore with a different execution_mode than
   * what the prop snapshot carries.
   */
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

    // Seed the state store with the authoritative execution_mode (as the
    // API fetch would populate it via setProject after the initial prop seed).
    const projectStateStore = useProjectStateStore()
    projectStateStore.setProject({
      id: projectId,
      project_id: projectId,
      execution_mode: storeMode,
      staging_status: 'staging_complete',
    })

    // Also seed the agent jobs store with a non-orchestrator specialist
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
    // Prop snapshot is stale (CLI mode from before re-staging)
    // Store holds the authoritative multi_terminal value
    const wrapper = await mountWithMode({ propMode: 'claude_code_cli', storeMode: 'multi_terminal' })

    // Phase badge must NOT show "All" (which only appears in subagent/CLI mode)
    // Phase badge for orchestrator must show "Start" (multi_terminal mode)
    const phaseBadges = wrapper.findAll('[data-testid="phase-badge"]')
    const allBadge = phaseBadges.find(b => b.text() === 'All')
    expect(allBadge, 'phase badge should not be "All" in multi_terminal mode').toBeUndefined()
  })

  it('[FE-6019] isSubagentMode is true when store has CLI mode', async () => {
    // Both prop and store agree: CLI mode
    const wrapper = await mountWithMode({ propMode: 'claude_code_cli', storeMode: 'claude_code_cli' })

    // At least one phase badge should be "All" (subagent mode)
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

// ---------------------------------------------------------------------------
// FE-9122: projectStore.updateProject's _upsertEntity bridge (products sibling:
// FE-9121) must keep JobsTab's store-first execution_mode read (FE-6019) fresh
// end-to-end through the real re-pick flow — unstage -> re-pick -> stage — with
// NO direct projectStateStore write anywhere in the path (the deleted
// setExecutionMode bandage). This is the component-level proof that Change 1 +
// Change 2 (the bridge + the composable's store-owning write path) compose.
// ---------------------------------------------------------------------------

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

    // Seed the store as the mount-time hydration would (multi_terminal, staged).
    const projectStateStore = useProjectStateStore()
    projectStateStore.setProject({
      id: projectId,
      project_id: projectId,
      execution_mode: 'multi_terminal',
      staging_status: 'staging_complete',
    })

    // Seed a specialist agent so a phase badge actually renders.
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

    // Drive the real unstage -> re-pick -> stage re-pick flow through
    // projectStore.updateProject (what useExecutionMode.handleExecutionModeChange
    // now calls) — not a direct projectStateStore write.
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

// ---------------------------------------------------------------------------
// BE-6200 (#6 follow-up): the chain conductor must never render in a project's
// agent lane. The leaked row was the conductor's pre-spawned impl-phase
// execution, which carries a REAL project_id — so the filter cannot key on
// project_id IS NULL. It keys on the flat `chain_conductor` field the API now
// serializes (NOT job_metadata, which is unserialized + clobbered by WS).
// ---------------------------------------------------------------------------

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
      // Conductor's pre-spawned impl-phase execution: REAL project_id, flat flag.
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

// ---------------------------------------------------------------------------
// BE-6229: the conductor leak vector is the WebSocket store path — a live
// upsertJob() into the GLOBAL jobs store WITHOUT a project-scoped setJobs()
// reload (nav-away re-hydration is what masked the bug before). These tests
// drive that exact path: seed the open project's agents, then upsertJob a
// conductor/foreign row as a live WS event would, and assert it never renders.
// ---------------------------------------------------------------------------

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

    // Live WS event: the conductor's row arrives WITH the flag now riding the
    // payload (the BE fix), upserted into the shared store with NO reload.
    agentJobsStore.upsertJob({
      job_id: 'job-conductor',
      agent_id: 'agent-conductor',
      agent_display_name: 'conductor',
      status: 'working',
      project_id: mockProject.project_id, // even matching project_id must not render
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

    // Old/forgetful WS path: a project-less conductor row with NO chain_conductor
    // flag (project_id null). The project_id guard must still drop it.
    agentJobsStore.upsertJob({
      job_id: 'job-conductor-noflag',
      agent_id: 'agent-conductor-noflag',
      agent_display_name: 'conductor',
      status: 'working',
      project_id: null,
    })
    // A foreign project's agent leaking via WS must also be dropped.
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
