/**
 * JobsTab.0904.spec.js — FE-9296b: the auto check-in slider is RETIRED.
 *
 * Handover 0904 introduced the per-project slider these tests used to pin.
 * FE-9296b removes it from the Jobs tab entirely (the Hub composer half left in
 * FE-9365d): the cadence is an account-level Settings value now (Tools →
 * Notifications), and slider-era per-project auto_checkin_* values are still
 * READ server-side as overrides — the columns stay, only the control goes.
 *
 * These are absence tests in the FE-9365d idiom: they pin that the control does
 * not come back, in the exact states where it used to render.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsTab from '@/components/projects/JobsTab.vue'
import { useProjectStateStore } from '@/stores/projectStateStore'
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
    projects: { update: vi.fn().mockResolvedValue({ data: {} }) },
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
  AgentDetailsModal: true,
  AgentJobModal: true,
  HandoverModal: true,
}

describe('JobsTab auto check-in slider — retired (FE-9296b)', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)

    const userStore = useUserStore()
    userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-1' }
  })

  it('renders no slider in multi-terminal after staging — the state where it used to show', async () => {
    const projectStateStore = useProjectStateStore()
    projectStateStore.setStagingComplete('proj-mt', true)

    const wrapper = mount(JobsTab, {
      props: {
        project: {
          project_id: 'proj-mt',
          id: 'proj-mt',
          name: 'MT Project',
          execution_mode: 'multi_terminal',
          auto_checkin_enabled: true,
          auto_checkin_interval: 30,
        },
      },
      global: { plugins: [pinia, vuetify, hubRouter], stubs },
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="auto-checkin"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="auto-checkin-slider"]').exists()).toBe(false)
  })

  it('tolerates slider-era auto_checkin_* values on the project row without rendering a control', async () => {
    // A row that already carries a non-default cadence must load cleanly —
    // the columns are still read server-side as an override (tolerance, not
    // migration) — while offering no per-project dial to compete with the
    // account-level Settings value.
    const projectStateStore = useProjectStateStore()
    projectStateStore.setStagingComplete('proj-legacy', true)

    const wrapper = mount(JobsTab, {
      props: {
        project: {
          project_id: 'proj-legacy',
          id: 'proj-legacy',
          name: 'Legacy Cadence Project',
          execution_mode: 'multi_terminal',
          auto_checkin_enabled: true,
          auto_checkin_interval: 60,
        },
      },
      global: { plugins: [pinia, vuetify, hubRouter], stubs },
    })
    await wrapper.vm.$nextTick()

    // The tab still renders its core content (the row did not break the mount)…
    expect(wrapper.find('[data-testid="agent-status-table"]').exists()).toBe(true)
    // …and no cadence control of any kind is offered.
    expect(wrapper.find('[data-testid="auto-checkin"]').exists()).toBe(false)
  })
})
