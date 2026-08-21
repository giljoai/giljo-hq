/**
 * CE-0028b / CE-0029 / CE-0032 — staging→implementation handoff status display.
 *
 * Historical evolution:
 *   - Pre-CE-0029: only orch row was the staging exec (status='complete')
 *     and applyStagingHandoffStatusOverride rewrote it to 'waiting' in the
 *     UI. CE-0029 removed the override.
 *   - CE-0029 Item 2: backend pre-spawned a SECOND orch exec ('waiting',
 *     phase='implementation') at staging-end so the UI naturally showed a
 *     waiting row.
 *   - CE-0032: REVERTED CE-0029 Item 2. The orchestrator is a single entity
 *     with one execution row whose status transitions across phases. At
 *     staging-end the backend leaves that single row at status='waiting' —
 *     the table shows ONE row, not two.
 *
 * These tests verify the post-CE-0032 reality:
 *   - Single orch row in status='waiting' renders as "Waiting" with no
 *     override function (the override is gone, store-fed status is rendered
 *     verbatim).
 *   - A working orch row renders as "Working", a complete orch (post-impl)
 *     renders as "Complete", non-orch agents render their actual status.
 *
 * Per feedback_frontend_prop_vs_store_source_of_truth, store state changes
 * are fed through the agent store mutation path, not by injecting fields
 * onto the prop. The prop carries only stable identifying fields.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsTab from '@/components/projects/JobsTab.vue'
import { useAgentJobsStore } from '@/stores/agentJobsStore'
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

vi.mock('@/services/api', () => {
  const api = {
    agentJobs: { list: vi.fn().mockResolvedValue({ data: [] }) },
    prompts: { agentPrompt: vi.fn().mockResolvedValue({ data: { prompt: '' } }) },
    messages: { sendUnified: vi.fn().mockResolvedValue({ data: { success: true } }) },
  }
  return { default: api, api }
})

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

const stubs = {
  'v-tooltip': true,
  'v-dialog': true,
  'v-card': true,
  'v-card-title': true,
  'v-card-text': true,
  'v-card-actions': true,
  'v-spacer': true,
  'v-text-field': true,
  'v-icon': true,
  'v-avatar': true,
  'v-btn': true,
  AgentDetailsModal: true,
  AgentJobModal: true,
  HandoverModal: true,
}

function makeProject(overrides = {}) {
  return {
    project_id: 'proj-1',
    id: 'proj-1',
    name: 'CE-0029 Test Project',
    execution_mode: 'multi_terminal',
    ...overrides,
  }
}

async function mountWithJobs(project, jobs) {
  const wrapper = mount(JobsTab, {
    props: { project },
    global: { plugins: [createPinia(), vuetify, hubRouter], stubs },
  })
  await wrapper.vm.$nextTick()
  const store = useAgentJobsStore()
  // BE-6229: real agent rows always carry the open project's project_id; the
  // JobsTab project-scope guard drops project-less rows (the chain conductor).
  store.setJobs(jobs.map((j) => ({ project_id: project.project_id, ...j })))
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('JobsTab CE-0032 staging→implementation handoff (single-exec, no-override)', () => {
  beforeEach(() => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-1' }
  })

  it('renders the single orch row in waiting status WITHOUT any override', async () => {
    // Post-CE-0032 reality: single orchestrator entity. At staging-end the
    // backend leaves the one orch exec row at status='waiting' (no second
    // row spawned; the CE-0029 Item 2 pre-spawn was removed). The UI shows
    // exactly one orch row, status 'Waiting', with no relabel.
    const project = makeProject()
    const wrapper = await mountWithJobs(project, [
      {
        job_id: 'j-orch',
        agent_id: 'a-orch',
        agent_name: 'orchestrator',
        agent_display_name: 'orchestrator',
        status: 'waiting',
        phase: null,
      },
    ])

    const rows = wrapper.findAll('[data-testid="agent-row"]')
    expect(rows.length).toBe(1)
    expect(rows[0].attributes('data-agent-status')).toBe('waiting')
    expect(rows[0].find('[data-testid="status-chip"]').text()).toContain('Waiting')
  })

  it('does not rewrite a working orchestrator', async () => {
    const project = makeProject()
    const wrapper = await mountWithJobs(project, [
      {
        job_id: 'j-orch',
        agent_id: 'a-orch',
        agent_name: 'orchestrator',
        agent_display_name: 'orchestrator',
        status: 'working',
        phase: null,
      },
    ])

    const row = wrapper.find('[data-testid="agent-row"]')
    expect(row.attributes('data-agent-status')).toBe('working')
    expect(row.find('[data-testid="status-chip"]').text()).toContain('Working')
  })

  it('does not rewrite a complete orchestrator post-implementation', async () => {
    // After implementation finishes there is no pre-spawn — the impl orch
    // exec is genuinely complete. The table must render that as-is, no
    // relabel to 'waiting'.
    const project = makeProject()
    const wrapper = await mountWithJobs(project, [
      {
        job_id: 'j-orch',
        agent_id: 'a-orch',
        agent_name: 'orchestrator',
        agent_display_name: 'orchestrator',
        status: 'complete',
        phase: null,
      },
    ])

    const row = wrapper.find('[data-testid="agent-row"]')
    expect(row.attributes('data-agent-status')).toBe('complete')
    expect(row.find('[data-testid="status-chip"]').text()).toContain('Complete')
  })

  it('does not rewrite non-orchestrator complete agents', async () => {
    const project = makeProject()
    const wrapper = await mountWithJobs(project, [
      {
        job_id: 'j-impl',
        agent_id: 'a-impl',
        agent_name: 'backend-implementer',
        agent_display_name: 'backend-implementer',
        status: 'complete',
        phase: 1,
      },
    ])

    const row = wrapper.find('[data-testid="agent-row"]')
    expect(row.attributes('data-agent-status')).toBe('complete')
    expect(row.find('[data-testid="status-chip"]').text()).toContain('Complete')
  })
})
