/**
 * JobsTab.0829.spec.js
 *
 * Handover 0829: Phase Column & Sort Order in Jobs Tab
 *
 * Tests:
 * 1. Table rows render in phase order (Orchestrator -> P1 -> P2 -> unphased)
 * 2. Phase badges show correct values per row
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

const mockProject = {
  project_id: 'proj-1',
  id: 'proj-1',
  name: 'Test Project',
  execution_mode: 'multi_terminal',
}

describe('JobsTab Phase Column (0829)', () => {
  let pinia, agentJobsStore

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)

    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-1' }

    agentJobsStore = useAgentJobsStore()
  })

  it('renders phase badges and sorts rows by phase order', async () => {
    const wrapper = mount(JobsTab, {
      props: { project: mockProject },
      global: { plugins: [pinia, vuetify, hubRouter], stubs },
    })
    await wrapper.vm.$nextTick()

    // Seed store AFTER mount so the loadJobs watcher doesn't overwrite
    // BE-6229: real agent rows always carry the open project's project_id; the
    // JobsTab project-scope guard drops project-less rows (the chain conductor).
    agentJobsStore.setJobs([
      { job_id: 'j1', agent_id: 'a1', project_id: 'proj-1', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working', phase: null },
      { job_id: 'j2', agent_id: 'a2', project_id: 'proj-1', agent_name: 'file-creator', agent_display_name: 'file-creator', status: 'waiting', phase: 2 },
      { job_id: 'j3', agent_id: 'a3', project_id: 'proj-1', agent_name: 'folder-creator', agent_display_name: 'folder-creator', status: 'waiting', phase: 1 },
      { job_id: 'j4', agent_id: 'a4', project_id: 'proj-1', agent_name: 'reviewer', agent_display_name: 'reviewer', status: 'waiting', phase: null },
    ])
    await wrapper.vm.$nextTick()

    const rows = wrapper.findAll('[data-testid="agent-row"]')
    expect(rows.length).toBe(4)

    // Verify sort order: orchestrator first, then P1, P2, unphased last
    expect(rows[0].attributes('data-agent-display-name')).toBe('orchestrator')
    expect(rows[1].attributes('data-agent-display-name')).toBe('folder-creator')
    expect(rows[2].attributes('data-agent-display-name')).toBe('file-creator')
    expect(rows[3].attributes('data-agent-display-name')).toBe('reviewer')

    // Verify phase badge content
    const badges = wrapper.findAll('[data-testid="phase-badge"]')
    expect(badges[0].text()).toBe('Start') // orchestrator shows "Start"
    expect(badges[1].text()).toBe('P1')
    expect(badges[2].text()).toBe('P2')
    expect(badges[3].text()).toBe('—') // unphased shows dash
  })
})
