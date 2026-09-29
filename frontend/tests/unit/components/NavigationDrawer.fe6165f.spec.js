/**
 * NavigationDrawer.vue — the Jobs nav item's destination
 *
 * FE-9655e: one landing. The item used to resolve per product data (a chain run,
 * a solo project, several, none); it now points at the Jobs board in every case,
 * so these tests hold the store in each of those states and assert the same path.
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

describe('NavigationDrawer.vue — the Jobs nav item always opens the board (FE-9655e)', () => {
  let pinia

  beforeEach(() => {
    // Create a fresh pinia per test and set it active so useSequenceRunStore()
    // in both the test and the component resolve to the same instance.
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
  })

  it('an in-flight chain run does not send Jobs to a member project', async () => {
    const wrapper = mountDrawer(pinia)
    await flushPromises()

    const store = useSequenceRunStore()
    store._testSeedRuns([{ id: 'r1', project_ids: ['p1'], status: 'running' }])
    await wrapper.vm.$nextTick()

    const path = jobsPath(wrapper)
    expect(path).toBe('/jobs-overview')
    expect(path).not.toContain('/projects/')
    expect(path).not.toContain('/mission-control')
  })

  it('a run carrying resolved_order still resolves to the board, with no run query', async () => {
    const wrapper = mountDrawer(pinia)
    await flushPromises()

    const store = useSequenceRunStore()
    store._testSeedRuns([
      { id: 'r2', project_ids: ['p1', 'p2'], resolved_order: ['head', 'p2'], status: 'pending' },
    ])
    await wrapper.vm.$nextTick()

    expect(jobsPath(wrapper)).toBe('/jobs-overview')
  })

  it('nothing in flight still resolves to the board, which carries its own empty state', async () => {
    const wrapper = mountDrawer(pinia)
    await flushPromises()

    const path = jobsPath(wrapper)
    expect(path).toBe('/jobs-overview')
    expect(path).not.toContain('/launch')
  })
})
