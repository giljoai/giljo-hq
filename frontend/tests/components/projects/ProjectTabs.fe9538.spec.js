/**
 * ProjectTabs.fe9538.spec.js — FE-9538 (Ask 2)
 *
 * The decision banner must navigate to somewhere that actually opens the
 * decision UI, not just to the project's page. By call path: ApprovalCard is
 * hosted by DecisionModal (NOT CloseoutModal, as the work order described --
 * corrected after reading ProjectTabs.vue directly), and showDecisionModal is
 * component-local state with no route-driven entry point before this fix.
 * SystemStatusBanner's openApprovals() now navigates with
 * `query: { tab: 'jobs', decide: '1' }`; this file pins the OTHER half --
 * ProjectTabs consuming `decide=1` on arrival to select the Jobs tab, open
 * the DecisionModal, and strip the param so switching tabs afterward never
 * reopens it.
 *
 * Harness mirrors ProjectTabs.closeout.spec.js.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import ProjectTabs from '@/components/projects/ProjectTabs.vue'

const mockRouter = { push: vi.fn(), replace: vi.fn() }
const mockRoute = { query: {}, hash: '' }

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => mockRouter,
}))

vi.mock('@/composables/useAgentJobs', () => ({
  useAgentJobs: () => ({
    store: {},
    sortedJobs: { value: [] },
    loadJobs: vi.fn().mockResolvedValue([]),
  }),
}))

vi.mock('@/composables/useIntegrationStatus', () => ({
  useIntegrationStatus: () => ({
    gitEnabled: { value: false },
    serenaEnabled: { value: false },
  }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }),
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    subscribeToProject: vi.fn(),
    unsubscribe: vi.fn(),
    onConnectionChange: vi.fn().mockReturnValue(vi.fn()),
    on: vi.fn().mockReturnValue(vi.fn()),
  }),
}))

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ clearForProject: vi.fn() }),
}))

vi.mock('@/services/api', () => ({
  default: {
    projects: {
      get: vi.fn().mockResolvedValue({
        data: {
          id: 'proj-1',
          project_id: 'proj-1',
          name: 'Test Project',
          description: 'Test',
          status: 'active',
          product_id: 'prod-1',
          staging_status: null,
          implementation_launched_at: null,
          execution_mode: 'multi_terminal',
          mission: '',
          alias: 'BE-0001',
          agent_count: 0,
          message_count: 0,
          agents: [],
        },
      }),
      update: vi.fn().mockResolvedValue({}),
    },
    prompts: { staging: vi.fn().mockResolvedValue({ data: { prompt: 'test' } }) },
    orchestrator: { launchProject: vi.fn().mockResolvedValue({}) },
    products: { getMemoryEntries: vi.fn().mockResolvedValue({ data: { entries: [] } }) },
  },
}))

function createWrapper({ query = {} } = {}) {
  const vuetify = createVuetify()
  mockRoute.query = query
  mockRoute.hash = ''

  return mount(ProjectTabs, {
    props: {
      project: {
        id: 'proj-1',
        project_id: 'proj-1',
        name: 'Test Project',
        description: 'Test',
        status: 'active',
        product_id: 'prod-1',
        execution_mode: 'multi_terminal',
      },
      orchestrator: null,
    },
    global: {
      plugins: [vuetify],
      stubs: {
        LaunchTab: { template: '<div class="launch-tab-stub" />' },
        JobsTab: { template: '<div class="jobs-tab-stub" />' },
        CloseoutModal: {
          template: '<div class="closeout-modal-stub" />',
          props: ['show'],
        },
        DecisionModal: {
          name: 'DecisionModal',
          template: '<div class="decision-modal-stub" />',
          props: ['show', 'orchestratorJobId'],
          emits: ['close', 'approval-decided'],
        },
      },
    },
  })
}

describe('ProjectTabs — decide=1 query consumption (FE-9538, Ask 2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockRouter.push.mockClear()
    mockRouter.replace.mockClear()
  })

  it('opens the DecisionModal on arrival when the URL carries decide=1', async () => {
    const wrapper = createWrapper({ query: { tab: 'jobs', decide: '1' } })
    await flushPromises()

    const modal = wrapper.findComponent({ name: 'DecisionModal' })
    expect(modal.props('show')).toBe(true)
  })

  it('strips decide from the URL so it is a one-shot, not reopened on tab switches', async () => {
    createWrapper({ query: { tab: 'jobs', decide: '1' } })
    await flushPromises()

    expect(mockRouter.replace).toHaveBeenCalledWith({ query: { tab: 'jobs' } })
  })

  it('does NOT open the DecisionModal when decide is absent (ordinary navigation)', async () => {
    const wrapper = createWrapper({ query: { tab: 'jobs' } })
    await flushPromises()

    const modal = wrapper.findComponent({ name: 'DecisionModal' })
    expect(modal.props('show')).toBe(false)
    expect(mockRouter.replace).not.toHaveBeenCalled()
  })
})
