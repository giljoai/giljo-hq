/**
 * NavigationDrawer.vue — FE-9501b (D5: the "Projects" nav badge)
 *
 * The activity surface for a project you do not have open, visible from ANY
 * page (NavigationDrawer is mounted app-wide in DefaultLayout). Reuses the
 * existing Hub-unread-badge shape/style. Ruling 14: visualization only -- the
 * badge itself never navigates; the item's pre-existing router-link is the
 * only navigation, and only on a click.
 *
 * FE-9366: the badge lives in v-list-item's #append named slot, which
 * tests/setup.js's flat VListItem stub renders NOTHING for (it only forwards
 * the default slot) -- exactly the class of bug FE-9365d shipped through 21
 * green tests. This file uses withRealVuetify() so the assertions exercise
 * the actual slot, not a stub that would pass unconditionally.
 *
 * Edition Scope: Both
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { useGlobalActivityStore } from '@/stores/globalActivityStore'
import { withRealVuetify } from '../../helpers/realVuetify.js'

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

// FE-9502d: the badge is now scoped to the VIEWED product's own projects
// (globalActivity is keyed by project_id across ALL products, so summing it
// unscoped badges a nav item that only ever lists the viewed product's
// projects with activity from a product you aren't looking at). Tests set
// h.projectIds to whatever project ids should count as "in the current
// product" before recording activity.
const h = vi.hoisted(() => ({ projectIds: [] }))
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    projects: h.projectIds.map((id) => ({ id })),
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
  useCommHubStore: () => ({ yourTurnCount: 0, totalUnread: 0 }),
}))

vi.mock('axios', () => ({
  default: { post: vi.fn(() => Promise.resolve({ data: {} })) },
}))

vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: vi.fn(() => () => {}),
}))

vi.mock('@/services/api', () => ({
  default: {
    sequenceRuns: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
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

vi.mock('@/composables/useApiUrl', () => ({
  getApiBaseUrl: () => 'http://localhost:8000',
}))

import NavigationDrawer from '@/components/navigation/NavigationDrawer.vue'

const testRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/home', name: 'Home', component: { template: '<div />' } },
    { path: '/Dashboard', name: 'Dashboard', component: { template: '<div />' } },
    { path: '/Products', name: 'Products', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
    { path: '/roadmap', name: 'Roadmap', component: { template: '<div />' } },
    { path: '/launch', name: 'Launch', component: { template: '<div />' } },
    { path: '/tasks', name: 'Tasks', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
    { path: '/memory', name: 'Memory', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})

const REAL_COMPONENTS = ['VList', 'VListItem']

async function mountDrawer(piniaInstance) {
  const real = await withRealVuetify(REAL_COMPONENTS)
  await testRouter.push('/home')
  await testRouter.isReady()
  const wrapper = mount(NavigationDrawer, {
    props: {
      modelValue: true,
      rail: false,
      temporary: false,
      currentUser: { username: 'admin', role: 'admin', email: 'admin@test.com' },
    },
    global: {
      plugins: piniaInstance ? [piniaInstance, real.plugin, testRouter] : [real.plugin, testRouter],
      stubs: {
        'v-navigation-drawer': {
          template: '<div class="v-navigation-drawer"><slot /><slot name="append" /></div>',
        },
        NotificationDropdown: { template: '<div />' },
        ConnectionDebugDialog: { template: '<div />' },
        UserProfileDialog: { template: '<div />' },
        RoleBadge: { template: '<span />' },
        NavLogMenu: { template: '<div />' },
        NavAvatarMenu: { template: '<div />' },
      },
    },
  })
  return { wrapper, restore: real.restore }
}

describe('NavigationDrawer.vue — FE-9501b Projects activity badge', () => {
  let pinia
  let restoreStubs

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
    h.projectIds = []
  })

  afterEach(() => {
    if (restoreStubs) restoreStubs()
    restoreStubs = null
  })

  it('renders no badge when there is no activity on unopened projects', async () => {
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()

    expect(wrapper.find('[data-testid="nav-projects-activity-badge"]').exists()).toBe(false)
  })

  it('renders the count once globalActivityStore records activity for a project in the viewed product', async () => {
    h.projectIds = ['proj-other']
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()

    useGlobalActivityStore().recordActivity('proj-other')
    await wrapper.vm.$nextTick()

    const badge = wrapper.find('[data-testid="nav-projects-activity-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('1')
  })

  it('sums activity across multiple unopened projects into one badge', async () => {
    h.projectIds = ['proj-a', 'proj-b']
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()

    const activity = useGlobalActivityStore()
    activity.recordActivity('proj-a')
    activity.recordActivity('proj-b')
    activity.recordActivity('proj-b')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="nav-projects-activity-badge"]').text()).toBe('3')
  })

  it('caps the displayed count at 99+', async () => {
    h.projectIds = ['proj-a']
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()

    const activity = useGlobalActivityStore()
    for (let i = 0; i < 150; i += 1) activity.recordActivity('proj-a')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="nav-projects-activity-badge"]').text()).toBe('99+')
  })

  it('recording activity never navigates away from the current route', async () => {
    h.projectIds = ['proj-other']
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()
    expect(testRouter.currentRoute.value.path).toBe('/home')

    useGlobalActivityStore().recordActivity('proj-other')
    await wrapper.vm.$nextTick()
    await flushPromises()

    // A pure store write must never move the route by itself -- only a click
    // on the (pre-existing, untouched) router-link does that.
    expect(testRouter.currentRoute.value.path).toBe('/home')
  })

  it('FE-9502d: does NOT count activity for a project belonging to a different (background) product', async () => {
    // The viewed product's project list contains only proj-mine; activity on
    // proj-other-product (a project the current fetch never scoped in,
    // because it belongs to a product that isn't viewed) must not inflate a
    // nav item that only ever lists proj-mine. That remainder surfaces on the
    // ProductTabStrip badge instead (productActivityStore, FE-9502d) -- not
    // silently dropped, just not counted HERE.
    h.projectIds = ['proj-mine']
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()

    const activity = useGlobalActivityStore()
    activity.recordActivity('proj-mine')
    activity.recordActivity('proj-other-product')
    activity.recordActivity('proj-other-product')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="nav-projects-activity-badge"]').text()).toBe('1')
  })
})
