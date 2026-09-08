/**
 * FE-9583 — DefaultLayout must not throw away a session the router guard just verified.
 *
 * This is the layer the bug was VISIBLE at, so the regression test lives here as
 * well as at the store: authGuard calls checkAuth() and gets a 200, navigation
 * to a protected route is allowed, DefaultLayout mounts and fires a SECOND
 * /api/auth/me through fetchCurrentUser(), and loadCurrentUser() turns any
 * falsey answer straight into router.push('/login'). With no transient
 * tolerance in the store, one indeterminate answer on that redundant request
 * bounced a live session to /login -- while the server journal showed
 * /api/auth/me 200 and /home 200 and no throttle refused anything.
 *
 * The fail-closed case is asserted alongside it: with nothing ever verified, an
 * indeterminate answer must STILL redirect. The fix preserves a verified
 * session; it never invents one.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { useUserStore } from '@/stores/user'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      me: vi.fn(),
    },
  },
  setTenantKey: vi.fn(),
  // DefaultLayout lazily installs the SaaS trial-guard interceptor, which
  // reaches for the raw axios instance. Provide it so that path is a clean
  // no-op instead of a caught-and-logged mock miss in the test output.
  apiClient: {
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}))

// Deterministic instead of leaning on setupService's module-level 2s cache.
vi.mock('@/services/setupService', () => ({
  default: {
    checkEnhancedStatus: vi.fn().mockResolvedValue({
      is_fresh_install: false,
      mode: 'ce',
      total_users_count: 1,
    }),
  },
}))

vi.mock('@/components/navigation/NavigationDrawer.vue', () => ({
  default: {
    name: 'NavigationDrawer',
    template: '<div>NavigationDrawer</div>',
    props: ['modelValue', 'rail', 'currentUser'],
    emits: ['update:modelValue', 'toggle-rail'],
  },
}))

vi.mock('@/components/ToastManager.vue', () => ({
  default: { name: 'ToastManager', template: '<div>ToastManager</div>' },
}))

vi.mock('@/components/LicensingDialog.vue', () => ({
  __esModule: true,
  default: {
    name: 'LicensingDialog',
    template: '<div>LicensingDialog</div>',
    __isTeleport: false,
    __isSuspense: false,
  },
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    connect: vi.fn().mockResolvedValue(),
    disconnect: vi.fn(),
  }),
}))

vi.mock('@/stores/websocketEventRouter', () => ({
  initWebsocketEventRouter: vi.fn(),
  registerReconnectResync: vi.fn(() => vi.fn()),
}))

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    fetchProjects: vi.fn().mockResolvedValue(),
  }),
}))

const mockFetch = vi.fn()
global.fetch = mockFetch

const VERIFIED_USER = { id: 7, username: 'admin', role: 'admin', tenant_key: 'tk_fe9583' }

function noResponseError() {
  const error = new Error('Network Error')
  error.code = 'ERR_NETWORK'
  return error
}

describe('FE-9583 DefaultLayout boot race', () => {
  let vuetify
  let wrapper
  let router
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify({ components, directives })
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/',
          name: 'dashboard',
          component: { template: '<div>Dashboard</div>' },
          meta: { layout: 'default', requiresAuth: true },
        },
        {
          path: '/login',
          name: 'login',
          component: { template: '<div>Login</div>' },
          meta: { layout: 'auth', requiresAuth: false },
        },
      ],
    })
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ is_fresh_install: false }),
    })
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
    vi.clearAllMocks()
  })

  // Exactly what authGuard does before the layout ever mounts.
  async function guardVerifiesSession() {
    const store = useUserStore()
    api.auth.me.mockResolvedValueOnce({ data: VERIFIED_USER })
    expect(await store.checkAuth()).toBe(true)
    return store
  }

  function mountLayout() {
    return mount(DefaultLayout, { global: { plugins: [vuetify, router, pinia] } })
  }

  it('does not redirect to /login when the second boot check comes back with no response', async () => {
    const store = await guardVerifiesSession()
    const push = vi.spyOn(router, 'push')

    // The redundant second /api/auth/me DefaultLayout fires on mount.
    api.auth.me.mockRejectedValue(noResponseError())

    wrapper = mountLayout()
    await flushPromises()

    const loginPushes = push.mock.calls.filter((call) => {
      const target = call[0]
      return target === '/login' || target?.path === '/login'
    })
    expect(loginPushes).toEqual([])
    expect(store.currentUser).toEqual(VERIFIED_USER)
  })

  it('does not redirect to /login when the second boot check is rate limited', async () => {
    const store = await guardVerifiesSession()
    const push = vi.spyOn(router, 'push')

    const throttled = new Error('Request failed with status code 429')
    throttled.response = { status: 429, data: {} }
    api.auth.me.mockRejectedValue(throttled)

    wrapper = mountLayout()
    await flushPromises()

    const loginPushes = push.mock.calls.filter((call) => {
      const target = call[0]
      return target === '/login' || target?.path === '/login'
    })
    expect(loginPushes).toEqual([])
    expect(store.currentUser).toEqual(VERIFIED_USER)
  })

  // FAIL-CLOSED GUARD: no verified session means the redirect must still happen.
  it('still redirects to /login when no session was ever verified', async () => {
    const store = useUserStore()
    expect(store.currentUser).toBeNull()
    const push = vi.spyOn(router, 'push')

    api.auth.me.mockRejectedValue(noResponseError())

    wrapper = mountLayout()
    await flushPromises()

    const loginPushes = push.mock.calls.filter((call) => {
      const target = call[0]
      return target === '/login' || target?.path === '/login'
    })
    expect(loginPushes.length).toBeGreaterThan(0)
    expect(store.currentUser).toBeNull()
  })

  it('still redirects to /login on a genuine 401', async () => {
    const store = await guardVerifiesSession()
    const push = vi.spyOn(router, 'push')

    const unauthorized = new Error('Request failed with status code 401')
    unauthorized.response = { status: 401, data: {} }
    api.auth.me.mockRejectedValue(unauthorized)

    wrapper = mountLayout()
    await flushPromises()

    const loginPushes = push.mock.calls.filter((call) => {
      const target = call[0]
      return target === '/login' || target?.path === '/login'
    })
    expect(loginPushes.length).toBeGreaterThan(0)
    expect(store.currentUser).toBeNull()
  })
})
