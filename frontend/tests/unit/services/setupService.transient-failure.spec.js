/**
 * FE-9233 regression: a THROTTLED (429) or erroring (5xx) /api/setup/status
 * must never be read as "this box is a fresh install".
 *
 * Reported on the CE dogfood box 2026-07-19: hammering refresh tripped the
 * per-IP rate limiter (expected), and the app then rerouted a fully set-up
 * install to /welcome — the CreateAdminAccount wizard.
 *
 * Chain: setupService._fetchStatus() treated ANY non-OK response as
 * "endpoint failed" -> _fallbackStatus() -> CE branch returns
 * is_fresh_install: true -> authGuard.js PRIORITY 1 -> next('/welcome').
 *
 * The distinction this file pins: an HTTP response means the server is ALIVE
 * (transient), a fetch throw means nothing is listening (genuine first boot).
 *
 * TWO-SIDED BY DESIGN. The fetch-throw path is LOAD-BEARING: the CE installer
 * starts the frontend before the backend finishes booting, and the fresh-install
 * fallback is what carries a real first-boot user into the admin-creation
 * wizard. Tests below pin BOTH sides — do not "simplify" one away.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn(() => Promise.resolve()),
    getGiljoMode: vi.fn(() => 'ce'),
    get config() {
      return { giljo_mode: 'ce' }
    },
  },
}))

const httpResponse = (status, body = {}) =>
  Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })

const OK_CONFIGURED = {
  is_fresh_install: false,
  requires_admin_creation: false,
  show_public_landing: false,
  total_users_count: 3,
  route_signal: 'login',
  mode: 'ce',
}

describe('setupService transient failure (FE-9233)', () => {
  let originalFetch

  beforeEach(() => {
    originalFetch = global.fetch
    vi.resetModules()
  })

  afterEach(() => {
    global.fetch = originalFetch
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('429 with no cache does NOT claim a fresh install', async () => {
    global.fetch = vi.fn(() => httpResponse(429, { detail: 'Too Many Requests' }))

    const { default: setupService } = await import('@/services/setupService')
    const result = await setupService.checkEnhancedStatus()

    expect(result.is_fresh_install).toBe(false)
    expect(result.requires_admin_creation).toBe(false)
  })

  it('500 with no cache does NOT claim a fresh install', async () => {
    global.fetch = vi.fn(() => httpResponse(500, {}))

    const { default: setupService } = await import('@/services/setupService')
    const result = await setupService.checkEnhancedStatus()

    expect(result.is_fresh_install).toBe(false)
    expect(result.requires_admin_creation).toBe(false)
  })

  it('429 returns the last-known status even after the TTL expired', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => httpResponse(200, OK_CONFIGURED))
      .mockImplementation(() => httpResponse(429, {}))
    global.fetch = fetchMock

    const { default: setupService } = await import('@/services/setupService')
    const good = await setupService.checkEnhancedStatus()
    expect(good.total_users_count).toBe(3)

    // Push past the 5min TTL so the throttled re-fetch actually happens.
    vi.advanceTimersByTime(300001)
    const throttled = await setupService.checkEnhancedStatus()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(throttled.is_fresh_install).toBe(false)
    expect(throttled.total_users_count).toBe(3)
    expect(throttled.route_signal).toBe('login')
    vi.useRealTimers()
  })

  it('does not poison the cache with a transient result', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => httpResponse(429, {}))
      .mockImplementation(() => httpResponse(200, OK_CONFIGURED))
    global.fetch = fetchMock

    const { default: setupService } = await import('@/services/setupService')
    await setupService.checkEnhancedStatus()
    // The transient result must NOT have been written to _statusCache, so the
    // very next call retries the network rather than serving the neutral shape.
    const recovered = await setupService.checkEnhancedStatus()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(recovered.total_users_count).toBe(3)
    expect(recovered.route_signal).toBe('login')
  })

  // ---- TWO-SIDED: the genuine first-boot path must still work ----

  it('LOAD-BEARING: fetch throw with no cache still yields the CE fresh-install fallback', async () => {
    global.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))

    const { default: setupService } = await import('@/services/setupService')
    const result = await setupService.checkEnhancedStatus()

    // Installer boot: frontend is up before the backend. Connection refused
    // means nothing is listening, which on CE means an unconfigured box.
    expect(result.is_fresh_install).toBe(true)
    expect(result.requires_admin_creation).toBe(true)
  })
})

describe('authGuard end-to-end with the real setupService (FE-9233)', () => {
  let originalFetch
  let createAuthGuard
  let setupService
  let configService
  let next

  const makeRoute = (path) => ({
    path,
    fullPath: path,
    meta: { requiresAuth: true, layout: 'default' },
  })

  beforeEach(async () => {
    originalFetch = global.fetch
    vi.resetModules()
    setActivePinia(createPinia())

    vi.doMock('@/services/api', () => ({
      default: { auth: { me: vi.fn().mockResolvedValue({ data: { id: 1, username: 'patrik' } }) } },
      setTenantKey: vi.fn(),
    }))

    ;({ createAuthGuard } = await import('@/router/authGuard'))
    ;({ default: setupService } = await import('@/services/setupService'))
    configService = { getGiljoMode: vi.fn(() => 'ce') }
    next = vi.fn()
  })

  afterEach(() => {
    global.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('THE REPORTED BUG: a throttled set-up CE install is not rerouted to /welcome', async () => {
    // Prime the service the way a real session does: one good status first.
    global.fetch = vi.fn(() => httpResponse(200, OK_CONFIGURED))
    await setupService.checkEnhancedStatus()

    // Now the rate limiter kicks in and the cache has aged out.
    setupService.invalidateStatusCache()
    global.fetch = vi.fn(() => httpResponse(429, { detail: 'Too Many Requests' }))

    const guard = createAuthGuard({ setupService, configService })
    await guard(makeRoute('/home'), makeRoute('/'), next)

    expect(next).not.toHaveBeenCalledWith('/welcome')
    // Stronger than "not /welcome": the user must proceed to the route they
    // asked for, not be bounced to /login either. next() with no argument is
    // vue-router's "allow this navigation".
    expect(next).toHaveBeenCalledWith()
  })

  it('LOAD-BEARING: a genuine first boot (connection refused) still reaches /welcome', async () => {
    global.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))

    const guard = createAuthGuard({ setupService, configService })
    await guard(makeRoute('/home'), makeRoute('/'), next)

    expect(next).toHaveBeenCalledWith('/welcome')
  })
})

/**
 * FE-9233 item 3: the same transient-vs-definitive conflation lived a second
 * time in the auth chain. _doCheckAuth() was a bare catch-all, so a 429 on
 * /api/auth/me cleared the session and the guard bounced a throttled user to
 * /login. A 401/403 still must clear it — that is a real logout.
 */
describe('userStore.checkAuth transient failure (FE-9233)', () => {
  let useUserStore
  let api

  beforeEach(async () => {
    vi.resetModules()
    setActivePinia(createPinia())
    vi.doMock('@/services/api', () => ({
      default: { auth: { me: vi.fn() } },
      setTenantKey: vi.fn(),
    }))
    ;({ default: api } = await import('@/services/api'))
    ;({ useUserStore } = await import('@/stores/user'))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('429 keeps the existing session instead of logging the user out', async () => {
    const store = useUserStore()
    api.auth.me.mockResolvedValueOnce({ data: { id: 1, username: 'patrik', tenant_key: 't1' } })
    expect(await store.checkAuth()).toBe(true)

    api.auth.me.mockRejectedValue({ response: { status: 429 } })
    // Bypass the 5s success TTL so the throttled call actually happens.
    await new Promise((r) => setTimeout(r, 0))
    store.currentUser = { id: 1, username: 'patrik', tenant_key: 't1' }

    const result = await store.checkAuth()
    expect(store.currentUser).not.toBeNull()
    expect(result).toBe(true)
  })

  it('503 keeps the existing session', async () => {
    const store = useUserStore()
    store.currentUser = { id: 1, username: 'patrik' }
    api.auth.me.mockRejectedValue({ response: { status: 503 } })

    expect(await store.checkAuth()).toBe(true)
    expect(store.currentUser).not.toBeNull()
  })

  it('429 with no prior session is still unauthenticated (no fabricated auth)', async () => {
    const store = useUserStore()
    store.currentUser = null
    api.auth.me.mockRejectedValue({ response: { status: 429 } })

    expect(await store.checkAuth()).toBe(false)
  })

  it('LOAD-BEARING: 401 still clears the session (a real logout must log out)', async () => {
    const store = useUserStore()
    store.currentUser = { id: 1, username: 'patrik' }
    api.auth.me.mockRejectedValue({ response: { status: 401 } })

    expect(await store.checkAuth()).toBe(false)
    expect(store.currentUser).toBeNull()
  })

  it('LOAD-BEARING: a network throw still clears the session', async () => {
    const store = useUserStore()
    store.currentUser = { id: 1, username: 'patrik' }
    api.auth.me.mockRejectedValue(new TypeError('Failed to fetch'))

    expect(await store.checkAuth()).toBe(false)
    expect(store.currentUser).toBeNull()
  })
})
