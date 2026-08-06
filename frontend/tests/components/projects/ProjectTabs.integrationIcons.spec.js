/**
 * ProjectTabs.integrationIcons.spec.js -- TSK-9234
 *
 * The integration-status icons rendered a CONCLUSION from unproven data: because
 * gitEnabled/serenaEnabled default to false, the Git and Serena icons appeared in
 * their disabled treatment -- tooltip "click to enable" -- before anything had
 * been read. Same class as the FE-9233 nudge, milder surface (passive icons, not
 * a call to action).
 *
 * Two layers, deliberately:
 *   1. LaunchTab renders the neutral pending treatment while unresolved, and the
 *      real status only once resolved.
 *   2. ProjectTabs actually WIRES the composable's `resolved` through to
 *      LaunchTab. Without this, layer 1 would keep passing if the binding were
 *      dropped -- the icons would silently regress.
 *
 * Layer 2 drives the pending window with a caller-controlled deferred: the
 * status promise stays unsettled until the test resolves it, so the pending
 * assertion is deterministic rather than a guessed moment. Asserting only the
 * post-resolution state would pass vacuously.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import LaunchTab from '@/components/projects/LaunchTab.vue'
import ProjectTabs from '@/components/projects/ProjectTabs.vue'

const { mockRouter, mockRoute, mockGetGitSettings, mockGetSerenaStatus } = vi.hoisted(() => ({
  mockRouter: { push: vi.fn(), replace: vi.fn() },
  mockRoute: { query: {}, hash: '' },
  mockGetGitSettings: vi.fn(),
  mockGetSerenaStatus: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => mockRouter,
}))

// NOTE: useIntegrationStatus is deliberately NOT mocked -- layer 2 exercises the
// real composable so this spec cannot drift from its actual resolved semantics.
vi.mock('@/services/setupService', () => ({
  default: {
    getGitSettings: mockGetGitSettings,
    getSerenaStatus: mockGetSerenaStatus,
  },
}))

vi.mock('@/composables/useAgentJobs', () => ({
  useAgentJobs: () => ({ store: {}, sortedJobs: { value: [] }, loadJobs: vi.fn().mockResolvedValue([]) }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }),
}))
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    subscribeToProject: vi.fn(),
    unsubscribe: vi.fn(),
    onConnectionChange: vi.fn().mockReturnValue(vi.fn()),
    on: vi.fn().mockImplementation(() => vi.fn()),
  }),
}))
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ clearForProject: vi.fn() }),
}))

const PROJECT = {
  id: 'proj-1',
  project_id: 'proj-1',
  name: 'Test Project',
  description: 'Test',
  product_id: 'prod-1',
  status: 'active',
  execution_mode: 'multi_terminal',
}

vi.mock('@/services/api', () => ({
  default: {
    projects: {
      get: vi.fn().mockResolvedValue({
        data: {
          ...{
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
        },
      }),
      update: vi.fn().mockResolvedValue({}),
    },
    prompts: { staging: vi.fn().mockResolvedValue({ data: { prompt: 'test' } }) },
    orchestrator: { launchProject: vi.fn().mockResolvedValue({}) },
    products: { getMemoryEntries: vi.fn().mockResolvedValue({ data: { entries: [] } }) },
  },
}))

// Real Vuetify v-tooltip renders its activator lazily, so the icons never reach
// the DOM under test-utils. The repo-standard fix is to stub it to a passthrough
// that renders BOTH the activator (the icon) and the default slot (the tooltip
// text) -- see ProjectTabs.spec.js / AccountStatusBadge.spec.js.
const globalStubs = {
  'v-tooltip': {
    template: '<div class="v-tooltip-stub"><slot name="activator" :props="{}" /><slot /></div>',
  },
}

function mountLaunchTab(props = {}) {
  return mount(LaunchTab, {
    props: { project: PROJECT, ...props },
    global: { plugins: [createVuetify()], stubs: globalStubs },
  })
}

/** A promise the test settles on demand, so the pending window is deterministic. */
function deferred() {
  let settle
  const promise = new Promise((resolve) => {
    settle = resolve
  })
  return { promise, settle }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockRoute.query = {}
})

describe('TSK-9234 -- integration icons do not render a status nobody has read', () => {
  describe('LaunchTab render states', () => {
    it('renders both icons neutral -- not disabled -- while the status is unresolved', () => {
      const wrapper = mountLaunchTab({
        gitEnabled: false,
        serenaEnabled: false,
        integrationsResolved: false,
      })

      const git = wrapper.find('[data-testid="git-status-icon"]')
      const serena = wrapper.find('[data-testid="serena-status-icon"]')

      // The icons still occupy their slot (no layout shift)...
      expect(git.exists()).toBe(true)
      expect(serena.exists()).toBe(true)
      // ...but must NOT claim "disabled" from the default-false state.
      expect(git.classes()).not.toContain('icon-disabled')
      expect(serena.classes()).not.toContain('icon-disabled')
      expect(git.classes()).toContain('icon-pending')
      expect(serena.classes()).toContain('icon-pending')
      // And the tooltip must not tell the user to go enable something.
      expect(wrapper.text()).not.toContain('Git disabled. Click to enable.')
      expect(wrapper.text()).not.toContain('Serena disabled. Click to enable.')
    })

    it('shows the real disabled treatment once resolved and genuinely off', () => {
      const wrapper = mountLaunchTab({
        gitEnabled: false,
        serenaEnabled: false,
        integrationsResolved: true,
      })

      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).toContain('icon-disabled')
      expect(wrapper.find('[data-testid="serena-status-icon"]').classes()).toContain('icon-disabled')
      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).not.toContain('icon-pending')
      expect(wrapper.text()).toContain('Git disabled. Click to enable.')
    })

    it('shows the enabled treatment once resolved and genuinely on', () => {
      const wrapper = mountLaunchTab({
        gitEnabled: true,
        serenaEnabled: true,
        integrationsResolved: true,
      })

      const git = wrapper.find('[data-testid="git-status-icon"]')
      expect(git.classes()).not.toContain('icon-disabled')
      expect(git.classes()).not.toContain('icon-pending')
      expect(wrapper.text()).toContain('Git integration enabled.')
    })

    it('defaults to the neutral state when the caller omits the flag entirely', () => {
      // Fail-safe: a consumer that forgets the prop renders "unknown", never a
      // false negative.
      const wrapper = mountLaunchTab({ gitEnabled: false, serenaEnabled: false })
      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).toContain('icon-pending')
      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).not.toContain('icon-disabled')
    })
  })

  describe('ProjectTabs wiring (real composable, caller-controlled pending window)', () => {
    it('keeps the icons neutral until the status fetch actually settles', async () => {
      const git = deferred()
      const serena = deferred()
      mockGetGitSettings.mockReturnValue(git.promise)
      mockGetSerenaStatus.mockReturnValue(serena.promise)

      const wrapper = mount(ProjectTabs, {
        props: { project: PROJECT },
        global: { plugins: [createVuetify()], stubs: globalStubs },
      })
      await flushPromises()

      // PENDING: the status promises are still unsettled by construction.
      const launchTab = wrapper.findComponent(LaunchTab)
      expect(launchTab.exists()).toBe(true)
      expect(launchTab.props('integrationsResolved')).toBe(false)
      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).toContain('icon-pending')

      // RESOLVE: now the status is genuinely known.
      git.settle({ enabled: true })
      serena.settle({ enabled: true })
      await flushPromises()

      expect(launchTab.props('integrationsResolved')).toBe(true)
      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).not.toContain('icon-pending')
      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).not.toContain('icon-disabled')
    })

    it('does not claim integrations are off when the status fetch ERRORS', async () => {
      // The transient-outage case: a fully-configured box must not be told its
      // integrations are disabled just because the read failed.
      vi.spyOn(console, 'error').mockImplementation(() => {})
      mockGetGitSettings.mockRejectedValue(new Error('429 throttled'))
      mockGetSerenaStatus.mockRejectedValue(new Error('429 throttled'))

      const wrapper = mount(ProjectTabs, {
        props: { project: PROJECT },
        global: { plugins: [createVuetify()], stubs: globalStubs },
      })
      await flushPromises()

      expect(wrapper.findComponent(LaunchTab).props('integrationsResolved')).toBe(false)
      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).not.toContain('icon-disabled')
      expect(wrapper.find('[data-testid="git-status-icon"]').classes()).toContain('icon-pending')
      expect(wrapper.text()).not.toContain('Git disabled. Click to enable.')
    })
  })
})
