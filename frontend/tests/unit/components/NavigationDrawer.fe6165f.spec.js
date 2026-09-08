/**
 * NavigationDrawer.vue — FE-6174c (Jobs-nav branch C reinstated → /jobs multi)
 *
 * FE-6173 removed branch C (which had pointed at the now-deleted /mission-control
 * route). FE-6174c REINSTATES it, but routing to the FE-6174b /jobs multi variant:
 *   - /projects/<headPid>?run=<id>  when an active chain run exists (branch C)
 *   - /projects/<id>?via=jobs       when no chain run but a solo project is active (branch A)
 *   - /launch?via=jobs              when neither (branch B)
 *
 * Edition Scope: CE
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

// ── service mocks (mirror NavigationDrawerModifications.spec.js) ──────────────
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn(() => Promise.resolve()),
    getGiljoMode: vi.fn(() => 'ce'),
    getEdition: vi.fn(() => 'community'),
    getVersion: vi.fn(() => '1.0.0'),
    isFallback: vi.fn(() => false),
    config: null,
  },
}))

vi.mock('@/services/setupService', () => ({
  default: {
    checkEnhancedStatus: vi.fn(() =>
      Promise.resolve({ is_fresh_install: false, total_users_count: 1 }),
    ),
  },
}))

// router — path /home, no ?via or ?run
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/home', query: {} }),
}))

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    projects: [],
    activeProject: null,
    activeProjects: [],
  }),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({ activeProduct: null }),
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { username: 'admin', role: 'admin', email: 'admin@test.com' },
    currentOrg: null,
    orgRole: null,
    isAdmin: false,
  }),
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    connectionStatus: 'connected',
    reconnectAttempts: 0,
    maxReconnectAttempts: 5,
    disconnect: vi.fn(),
  }),
}))

vi.mock('@/stores/commHubStore', () => ({
  useCommHubStore: () => ({ yourTurnCount: 0 }),
}))

vi.mock('axios', () => ({
  default: { post: vi.fn(() => Promise.resolve({ data: {} })) },
}))

// The websocketEventRouter is needed for registerReconnectResync
vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: vi.fn(() => () => {}),
}))

// Mock the api so hydrate() doesn't overwrite seeded runs.
// Returns [] (no active runs) unless a test overrides with _testSeedRuns.
vi.mock('@/services/api', () => ({
  default: {
    sequenceRuns: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
    },
  },
}))

// Composable mocks
vi.mock('@/composables/useNavDrawerAccount', () => ({
  useNavDrawerAccount: () => ({
    AccountStatusBadgeComponent: null,
    accountBadgeState: 'ok',
    isAccountScheduledForDeletion: false,
    accountBadgeStateModifier: '',
    accountStatusTitle: '',
    accountStatusSubtitle: '',
    cancellingDeletion: false,
    onCancelDeletion: vi.fn(),
    goUpgrade: vi.fn(),
    loadAccountStateUI: vi.fn(),
  }),
}))

vi.mock('@/composables/useNavConnectionStatus', () => ({
  useNavConnectionStatus: () => ({
    connectionIcon: 'mdi-circle',
    connectionColor: 'success',
    connectionText: 'Connected',
  }),
}))

vi.mock('@/composables/useApiUrl', () => ({
  getApiBaseUrl: () => 'http://localhost:8000',
}))

import NavigationDrawer from '@/components/navigation/NavigationDrawer.vue'

function mountDrawer(piniaInstance) {
  return mount(NavigationDrawer, {
    props: {
      modelValue: true,
      rail: false,
      temporary: false,
      currentUser: { username: 'admin', role: 'admin', email: 'admin@test.com' },
    },
    global: {
      plugins: piniaInstance ? [piniaInstance] : [],
      stubs: {
        'v-navigation-drawer': {
          template: '<div class="v-navigation-drawer"><slot /><slot name="append" /></div>',
        },
        'router-link': { template: '<a><slot /></a>' },
        NotificationDropdown: { template: '<div />' },
        ConnectionDebugDialog: { template: '<div />' },
        UserProfileDialog: { template: '<div />' },
        RoleBadge: { template: '<span />' },
        NavLogMenu: { template: '<div />' },
        NavAvatarMenu: { template: '<div />' },
      },
    },
  })
}

function jobsPath(wrapper) {
  const item = wrapper.vm.navigationItems.find((i) => i.name === 'Jobs')
  return item?.path
}

describe('NavigationDrawer.vue — Jobs-nav (FE-6174c: branch C → /jobs multi)', () => {
  let pinia

  beforeEach(() => {
    // Create a fresh pinia per test and set it active so useSequenceRunStore()
    // in both the test and the component resolve to the same instance.
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
  })

  it('branch C: an active chain run routes Jobs to the head project /jobs multi view', async () => {
    const wrapper = mountDrawer(pinia)
    await flushPromises()

    const store = useSequenceRunStore()
    store._testSeedRuns([{ id: 'r1', project_ids: ['p1'], status: 'running' }])
    await wrapper.vm.$nextTick()

    // FE-6174c: an active chain run resolves to /projects/<headPid>?run=<id>
    // (the /jobs multi variant). Head falls back to project_ids[0] when the
    // seeded run carries no resolved_order. It must NOT point at the retired
    // /mission-control route.
    const path = jobsPath(wrapper)
    expect(path).not.toContain('/mission-control')
    expect(path).toBe('/projects/p1?run=r1')
  })

  it('branch C: head comes from resolved_order[0] when present', async () => {
    const wrapper = mountDrawer(pinia)
    await flushPromises()

    const store = useSequenceRunStore()
    store._testSeedRuns([
      { id: 'r2', project_ids: ['p1', 'p2'], resolved_order: ['head', 'p2'], status: 'pending' },
    ])
    await wrapper.vm.$nextTick()

    expect(jobsPath(wrapper)).toBe('/projects/head?run=r2')
  })

  it('branch B: Jobs path = /launch?via=jobs when no chain run and no active project', async () => {
    const wrapper = mountDrawer(pinia)
    await flushPromises()

    const path = jobsPath(wrapper)
    expect(path).not.toContain('/mission-control')
    expect(path).toBe('/launch?via=jobs')
  })
})
