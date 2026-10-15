/**
 * NavigationDrawer.vue — FE-9751: the "Projects" nav item carries no activity
 * badge (it never reset and duplicated the banners); the Hub unread badge stays.
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
const h = vi.hoisted(() => ({ projectIds: [], hubUnread: 0 }))
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
  useCommHubStore: () => ({ yourTurnCount: 0, totalUnread: h.hubUnread }),
}))

vi.mock('axios', () => ({
  default: { post: vi.fn(() => Promise.resolve({ data: {} })) },
}))

vi.mock('@/stores/websocketEventRouter', async (importOriginal) => ({
  ...(await importOriginal()),
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

import { routeGlobalApprovalEvent } from '@/stores/websocketEventRouter'
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

describe('NavigationDrawer.vue — FE-9751 no Projects activity badge', () => {
  let pinia
  let restoreStubs

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
    h.projectIds = []
    h.hubUnread = 0
  })

  afterEach(() => {
    if (restoreStubs) restoreStubs()
    restoreStubs = null
  })

  it('renders no Projects badge when there is no activity', async () => {
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()

    expect(wrapper.find('[data-testid="nav-projects-activity-badge"]').exists()).toBe(false)
  })

  it('renders no Projects badge after agent and job events arrive for the viewed product', async () => {
    h.projectIds = ['proj-a', 'proj-b']
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()

    for (const type of ['agent:created', 'agent:status_changed', 'agent:removed', 'job:progress_update']) {
      routeGlobalApprovalEvent({ type, data: { project_id: 'proj-a' } })
      routeGlobalApprovalEvent({ type, data: { project_id: 'proj-b' } })
    }
    await wrapper.vm.$nextTick()
    await flushPromises()

    expect(wrapper.find('[data-testid="nav-projects-activity-badge"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/projects"]').exists()).toBe(true)
  })

  it('keeps the Hub unread badge when the Hub has unread threads', async () => {
    h.hubUnread = 4
    const { wrapper, restore } = await mountDrawer(pinia)
    restoreStubs = restore
    await flushPromises()

    const badge = wrapper.find('[data-testid="nav-hub-unread-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('4')
  })
})
