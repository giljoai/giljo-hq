/**
 * FE-9583 — an indeterminate auth result must not be treated as a proven logout.
 *
 * The boot race: the router guard verifies the session with a 200 from
 * /api/auth/me, navigation is allowed, then DefaultLayout mounts and fires a
 * SECOND, independent /api/auth/me via fetchCurrentUser(). That second call's
 * failure path had no transient tolerance at all -- any error, including one
 * carrying no response object, cleared currentUser and returned false, and
 * DefaultLayout turns that false into router.push('/login'). One blip on a
 * redundant request discarded a session the guard had just verified, which is
 * why the server journal showed /api/auth/me 200 and /home 200 while the
 * browser sat on /login with no throttle behind it.
 *
 * FE-9233 established the policy for the GATE (_doCheckAuth): a "not now" answer
 * from the server is not "you are logged out". This project extends the same
 * reasoning to the REFRESH, which never had it.
 *
 * Scope decision, deliberate: _doCheckAuth is NOT changed here. FE-9233 pinned
 * its network-throw behaviour as load-bearing on purpose --
 * tests/unit/services/setupService.transient-failure.spec.js draws the line at
 * "an HTTP response means the server is alive, a fetch throw means nothing is
 * listening" and says in its header not to simplify either side away. So the
 * gate keeps failing closed on a throw, and the last describe block below pins
 * that non-change so a later lane does not "finish the job" by relaxing it.
 *
 * What is fixed is narrower and does not touch the gate: a non-gate refresh
 * must not be able to revoke a verdict the gate has already reached. The
 * tolerance is conditional on a verified session existing, so with nothing
 * verified the original hard-fail path runs unchanged.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '@/stores/user'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      me: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
    },
  },
  setTenantKey: vi.fn(),
}))

const VERIFIED_USER = { id: 7, username: 'admin', role: 'admin', tenant_key: 'tk_fe9583' }

// An axios rejection with NO response object -- an aborted XHR, a connection
// reset, a DNS failure. This is the shape whose status is undefined.
function noResponseError() {
  const error = new Error('Network Error')
  error.code = 'ERR_NETWORK'
  return error
}

function httpError(status) {
  const error = new Error(`Request failed with status code ${status}`)
  error.response = { status, data: {} }
  return error
}

describe('FE-9583 user store: an indeterminate auth result is not a logout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // Reproduce the boot sequence: the guard's checkAuth() verifies the session
  // with a real 200 before the layout's fetchCurrentUser() ever runs.
  async function bootWithVerifiedSession() {
    const store = useUserStore()
    api.auth.me.mockResolvedValueOnce({ data: VERIFIED_USER })
    const verified = await store.checkAuth()
    expect(verified).toBe(true)
    expect(store.currentUser).toEqual(VERIFIED_USER)
    return store
  }

  describe('fetchCurrentUser() -- the path DefaultLayout turns into a redirect', () => {
    it('preserves a verified session when the second check comes back with no response', async () => {
      const store = await bootWithVerifiedSession()

      api.auth.me.mockRejectedValueOnce(noResponseError())
      const result = await store.fetchCurrentUser()

      // Without this, DefaultLayout.loadCurrentUser() sees false and pushes /login.
      expect(result).toBe(true)
      expect(store.currentUser).toEqual(VERIFIED_USER)
      expect(store.isAuthenticated).toBe(true)
    })

    it('preserves a verified session when the second check is rate limited', async () => {
      const store = await bootWithVerifiedSession()

      api.auth.me.mockRejectedValueOnce(httpError(429))
      const result = await store.fetchCurrentUser()

      expect(result).toBe(true)
      expect(store.currentUser).toEqual(VERIFIED_USER)
    })

    it('preserves a verified session when the second check hits a 503', async () => {
      const store = await bootWithVerifiedSession()

      api.auth.me.mockRejectedValueOnce(httpError(503))
      const result = await store.fetchCurrentUser()

      expect(result).toBe(true)
      expect(store.currentUser).toEqual(VERIFIED_USER)
    })

    // FAIL-CLOSED GUARD. Nothing below may ever start passing for the wrong reason.
    it('still denies when there was no verified session to preserve', async () => {
      const store = useUserStore()
      expect(store.currentUser).toBeNull()

      api.auth.me.mockRejectedValueOnce(noResponseError())
      const result = await store.fetchCurrentUser()

      expect(result).toBe(false)
      expect(store.currentUser).toBeNull()
      expect(store.isAuthenticated).toBe(false)
    })

    it('still clears the session on a genuine 401', async () => {
      const store = await bootWithVerifiedSession()

      api.auth.me.mockRejectedValueOnce(httpError(401))
      const result = await store.fetchCurrentUser()

      expect(result).toBe(false)
      expect(store.currentUser).toBeNull()
      expect(store.orgId).toBeNull()
    })

    it('still clears the session on a 403', async () => {
      const store = await bootWithVerifiedSession()

      api.auth.me.mockRejectedValueOnce(httpError(403))
      const result = await store.fetchCurrentUser()

      expect(result).toBe(false)
      expect(store.currentUser).toBeNull()
    })
  })

  // The gate's own classification is out of scope for FE-9583 and is pinned
  // here so this fix cannot quietly grow into a relaxation of it later.
  describe('checkAuth() gate behaviour is deliberately UNCHANGED', () => {
    it('still clears the session on a network throw (FE-9233, load-bearing)', async () => {
      const store = await bootWithVerifiedSession()
      vi.advanceTimersByTime(6000)

      api.auth.me.mockRejectedValueOnce(noResponseError())
      const result = await store.checkAuth()

      expect(result).toBe(false)
      expect(store.currentUser).toBeNull()
    })

    it('still keeps the session on a 429 (FE-9233)', async () => {
      const store = await bootWithVerifiedSession()
      vi.advanceTimersByTime(6000)

      api.auth.me.mockRejectedValueOnce(httpError(429))
      const result = await store.checkAuth()

      expect(result).toBe(true)
      expect(store.currentUser).toEqual(VERIFIED_USER)
    })

    it('still clears the session on a genuine 401', async () => {
      const store = await bootWithVerifiedSession()
      vi.advanceTimersByTime(6000)

      api.auth.me.mockRejectedValueOnce(httpError(401))
      const result = await store.checkAuth()

      expect(result).toBe(false)
      expect(store.currentUser).toBeNull()
    })
  })
})
