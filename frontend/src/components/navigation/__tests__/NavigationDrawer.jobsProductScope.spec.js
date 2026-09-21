import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

const HERMES = 'prod-hermes'
const YAPPER = 'prod-yapper'
const YAPPER_RUN = { id: 'run-yapper', project_ids: ['yapper-p1'], resolved_order: ['yapper-p1'], status: 'running' }

const h = vi.hoisted(() => ({
  viewedProductId: null,
  listRuns: vi.fn(),
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
  useRoute: () => ({ path: '/home', query: {} }),
}))

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({ projects: [], activeProject: null, activeProjects: [] }),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    activeProduct: null,
    get currentProduct() {
      return { id: h.viewedProductId.value }
    },
    get effectiveProductId() {
      return h.viewedProductId.value
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
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

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

function jobsPath(wrapper) {
  return wrapper.vm.navigationItems.find((i) => i.name === 'Jobs')?.path
}

describe('NavigationDrawer — Jobs nav follows the viewed product tab (FE-9627)', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    h.viewedProductId = ref(HERMES)
    h.listRuns.mockReset()
    h.listRuns.mockImplementation((params = {}) => {
      if (!params.product_id) return Promise.resolve({ data: [YAPPER_RUN] })
      return Promise.resolve({ data: params.product_id === YAPPER ? [YAPPER_RUN] : [] })
    })
  })

  it('scopes the mount-time hydrate to the viewed product', async () => {
    mountDrawer(pinia)
    await flushPromises()

    expect(h.listRuns).toHaveBeenCalled()
    expect(h.listRuns.mock.calls[0][0]).toMatchObject({ product_id: HERMES })
  })

  it('does not point Jobs at another product’s in-flight chain member', async () => {
    const wrapper = mountDrawer(pinia)
    await flushPromises()

    const path = jobsPath(wrapper)
    expect(path).not.toContain('yapper-p1')
    expect(path).not.toContain('run-yapper')
    expect(path).toBe('/launch?via=jobs')
  })

  it('does not let a chain opened from another product win the Jobs link', async () => {
    h.getRun.mockResolvedValue({
      data: {
        id: 'run-yapper-review',
        project_ids: ['yapper-p1'],
        resolved_order: ['yapper-p1'],
        project_statuses: { 'yapper-p1': 'completed' },
        status: 'stalled',
      },
    })
    const wrapper = mountDrawer(pinia)
    await flushPromises()

    await useSequenceRunStore(pinia).fetchRun('run-yapper-review')
    await flushPromises()

    const path = jobsPath(wrapper)
    expect(path).not.toContain('yapper-p1')
    expect(path).not.toContain('run-yapper-review')
    expect(path).toBe('/launch?via=jobs')
  })

  it('re-hydrates with the new product id when the tab switches', async () => {
    const wrapper = mountDrawer(pinia)
    await flushPromises()
    h.listRuns.mockClear()

    h.viewedProductId.value = YAPPER
    await flushPromises()

    expect(h.listRuns).toHaveBeenCalled()
    expect(h.listRuns.mock.calls.at(-1)[0]).toMatchObject({ product_id: YAPPER })
    expect(jobsPath(wrapper)).toBe('/projects/yapper-p1?run=run-yapper')
  })
})
