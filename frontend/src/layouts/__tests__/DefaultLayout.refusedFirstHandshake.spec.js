import { describe, it, expect, vi } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'

const connectionListeners = new Set()
const fakeWsStore = {
  connect: vi.fn(() => Promise.reject(new Error('Connection failed: Too many requests'))),
  disconnect: vi.fn(),
  on: vi.fn(() => () => {}),
  onConnectionChange: (listener) => {
    connectionListeners.add(listener)
    return () => connectionListeners.delete(listener)
  },
}
vi.mock('@/stores/websocket', () => ({ useWebSocketStore: () => fakeWsStore }))

const refreshList = vi.fn()
vi.mock('@/stores/projects', () => ({ useProjectStore: () => ({ refreshList }) }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ meta: { hideDrawer: true }, name: 'Welcome' }),
  useRouter: () => ({ push: vi.fn(), afterEach: vi.fn() }),
}))
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    fetchCurrentUser: async () => true,
    currentUser: { id: 'u1', tenant_key: 'tk_1' },
  }),
}))
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: [],
    openProductIds: [],
    openProductTabs: [],
    initializeFromStorage: async () => {},
  }),
}))
vi.mock('@/stores/jobsScope', () => ({ useJobsScopeStore: () => ({}) }))
vi.mock('@/stores/projectStatusesStore', () => ({
  useProjectStatusesStore: () => ({ ensureLoaded: async () => {} }),
}))
vi.mock('@/stores/taskStatusesStore', () => ({
  useTaskStatusesStore: () => ({ ensureLoaded: async () => {} }),
}))
vi.mock('@/services/setupService', () => ({
  default: { checkEnhancedStatus: async () => ({ is_fresh_install: false }) },
}))
vi.mock('@/composables/useHubNotifications', () => ({ useHubNotifications: () => {} }))
vi.mock('@/composables/useBannerPopoutLifecycle', () => ({ useBannerPopoutLifecycle: () => {} }))
vi.mock('@/composables/useActiveProductReconciliation', () => ({
  useActiveProductReconciliation: () => ({ stop: () => {} }),
}))
vi.mock('@/composables/useProductTabNavigation', () => ({
  useProductTabNavigation: () => ({ selectTab: () => {} }),
}))
vi.mock('@/composables/useGiljoMode', () => ({ useGiljoMode: () => ({ isSaasMode: () => false }) }))

describe('DefaultLayout: refused first WebSocket handshake', () => {
  it('a later reconnect still runs the reconnect resyncs', async () => {
    const DefaultLayout = (await import('@/layouts/DefaultLayout.vue')).default
    const wrapper = shallowMount(DefaultLayout, {
      global: {
        stubs: { 'router-view': true },
        mocks: { $route: { matched: [], path: '/welcome' } },
      },
    })
    await flushPromises()
    expect(fakeWsStore.connect).toHaveBeenCalledTimes(1)

    await Promise.all(
      Array.from(connectionListeners).map((listener) =>
        listener({ state: 'connected', isReconnect: true }),
      ),
    )
    await flushPromises()

    expect(refreshList).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
