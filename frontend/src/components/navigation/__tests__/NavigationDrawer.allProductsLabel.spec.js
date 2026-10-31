import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  route: { path: '/home', name: 'Home', query: {} },
  listRuns: vi.fn(() => Promise.resolve({ data: [] })),
  getRun: vi.fn(() => Promise.resolve({ data: {} })),
}))

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
    checkEnhancedStatus: vi.fn(() => Promise.resolve({ is_fresh_install: false, total_users_count: 1 })),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => h.route,
}))

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({ projects: [], activeProject: null, activeProjects: [] }),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    activeProduct: null,
    get currentProduct() {
      return { id: 'prod-yapper', name: 'GiljoAI Yapper' }
    },
    get effectiveProductId() {
      return 'prod-yapper'
    },
  }),
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

vi.mock('axios', () => ({ default: { post: vi.fn(() => Promise.resolve({ data: {} })) } }))

vi.mock('@/stores/websocketEventRouter', () => ({ registerReconnectResync: vi.fn(() => () => {}) }))

vi.mock('@/services/api', () => ({
  default: {
    sequenceRuns: {
      list: (...a) => h.listRuns(...a),
      get: (...a) => h.getRun(...a),
    },
  },
}))

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

vi.mock('@/composables/useApiUrl', () => ({ getApiBaseUrl: () => 'http://localhost:8000' }))

import NavigationDrawer from '@/components/navigation/NavigationDrawer.vue'
import { useJobsScopeStore } from '@/stores/jobsScope'

function mountDrawer(piniaInstance) {
  return mount(NavigationDrawer, {
    props: {
      modelValue: true,
      rail: false,
      temporary: false,
      currentUser: { username: 'admin', role: 'admin', email: 'admin@test.com' },
    },
    global: {
      plugins: [piniaInstance],
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

function subtitle(wrapper) {
  return wrapper.get('[data-testid="nav-product-subtitle"]').text()
}

describe('NavigationDrawer: the product label follows the All tab', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
  })

  it('reads All products on the Jobs board with All picked', async () => {
    h.route = { path: '/jobs-overview', name: 'JobsViewport', query: {} }
    const wrapper = mountDrawer(pinia)
    await flushPromises()
    expect(subtitle(wrapper)).toBe('All products')
  })

  it('names the viewed product once a product tab is picked on Jobs', async () => {
    h.route = { path: '/jobs-overview', name: 'JobsViewport', query: {} }
    const wrapper = mountDrawer(pinia)
    useJobsScopeStore().selectProduct()
    await flushPromises()
    expect(subtitle(wrapper)).toBe('GiljoAI Yapper')
  })

  it('names the viewed product on a page without the All tab', async () => {
    h.route = { path: '/hub', name: 'Hub', query: {} }
    const wrapper = mountDrawer(pinia)
    await flushPromises()
    expect(subtitle(wrapper)).toBe('GiljoAI Yapper')
  })
})
