/**
 * Unit tests for the real production auth guard used in router/index.js.
 *
 * Regression target: mcp.example.com 2026-04-24 -- clicking Logout then typing
 * `/home` in the address bar rendered the protected view without the router
 * calling /api/auth/me. Option A (per orchestrator mission): every protected
 * navigation must re-verify the session with the backend; on auth failure the
 * user store must be fully cleared and the user redirected to /login.
 *
 * The guard is factored out of router/index.js so it can be tested in
 * isolation. See frontend/src/router/authGuard.js.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '@/stores/user'
import { createAuthGuard } from '@/router/authGuard'

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

import api from '@/services/api'

describe('createAuthGuard — Option A (verify /api/auth/me on every protected nav)', () => {
  let guard
  let setupService
  let configService
  let next

  const makeRoute = (path, meta = {}) => ({
    path,
    fullPath: path,
    meta: { requiresAuth: true, layout: 'default', ...meta },
  })

  const makeRedirectedRoute = (path, redirectedFromPath, meta = {}) => ({
    ...makeRoute(path, meta),
    redirectedFrom: {
      path: redirectedFromPath,
      fullPath: redirectedFromPath,
    },
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()

    setupService = {
      checkEnhancedStatus: vi.fn().mockResolvedValue({
        is_fresh_install: false,
        total_users_count: 2,
        route_signal: null,
        show_public_landing: false,
        mode: 'ce',
      }),
    }
    configService = {
      getGiljoMode: vi.fn(() => 'ce'),
    }

    guard = createAuthGuard({ setupService, configService })
    next = vi.fn()
  })

  it('calls /api/auth/me every time for protected routes, even when store has a cached user', async () => {
    const store = useUserStore()
    store.currentUser = { username: 'stale', role: 'user' }

    api.auth.me.mockResolvedValue({
      data: { id: 1, username: 'stale', role: 'user' },
    })

    await guard(makeRoute('/home'), makeRoute('/'), next)

    // Session must always be re-validated with the backend on protected nav
    expect(api.auth.me).toHaveBeenCalledTimes(1)
    expect(next).toHaveBeenCalledWith()
  })

  it('redirects to /login when /api/auth/me fails (401 after logout)', async () => {
    const store = useUserStore()
    // Simulate the post-logout state: store cleared, but imagine a stale
    // cookie or race that could leave something cached.
    store.currentUser = null

    api.auth.me.mockRejectedValue({ response: { status: 401 } })

    await guard(makeRoute('/home'), makeRoute('/'), next)

    expect(next).toHaveBeenCalledWith({
      path: '/login',
      query: { redirect: '/home' },
    })
  })

  it('resets the user store when /api/auth/me fails after logout', async () => {
    const store = useUserStore()
    // Simulate stale state that survived an incomplete logout
    store.currentUser = { username: 'zombie', role: 'admin' }
    store.orgId = 'org-1'
    store.orgName = 'Zombie Org'
    store.orgRole = 'admin'

    api.auth.me.mockRejectedValue({ response: { status: 401 } })

    await guard(makeRoute('/home'), makeRoute('/'), next)

    // Guard must actively clear stale auth state so no component can
    // render based on userStore.currentUser after redirect
    expect(store.currentUser).toBeNull()
    expect(store.orgId).toBeNull()
    expect(store.orgName).toBeNull()
    expect(store.orgRole).toBeNull()
    expect(store.isAuthenticated).toBe(false)
    expect(next).toHaveBeenCalledWith({
      path: '/login',
      query: { redirect: '/home' },
    })
  })

  it('allows navigation when /api/auth/me succeeds', async () => {
    api.auth.me.mockResolvedValue({
      data: { id: 1, username: 'alice', role: 'user' },
    })

    await guard(makeRoute('/home'), makeRoute('/'), next)

    const store = useUserStore()
    expect(store.currentUser).toEqual({ id: 1, username: 'alice', role: 'user' })
    expect(next).toHaveBeenCalledWith()
  })

  it('does NOT call /api/auth/me for public routes (layout: auth, requiresAuth: false)', async () => {
    const loginRoute = {
      path: '/login',
      fullPath: '/login',
      meta: { layout: 'auth', requiresAuth: false },
    }

    await guard(loginRoute, makeRoute('/'), next)

    expect(api.auth.me).not.toHaveBeenCalled()
    expect(next).toHaveBeenCalledWith()
  })

  it('redirects non-admin users away from admin-only routes', async () => {
    api.auth.me.mockResolvedValue({
      data: { id: 1, username: 'alice', role: 'user' },
    })

    await guard(
      makeRoute('/admin/users', { requiresAuth: true, requiresAdmin: true }),
      makeRoute('/'),
      next,
    )

    // Redirect to Dashboard (matches router/index.js current behavior)
    expect(next).toHaveBeenCalledWith({ name: 'Dashboard' })
  })

  it('allows admin users to access admin-only routes after /api/auth/me succeeds', async () => {
    api.auth.me.mockResolvedValue({
      data: { id: 2, username: 'root', role: 'admin' },
    })

    await guard(
      makeRoute('/admin/users', { requiresAuth: true, requiresAdmin: true }),
      makeRoute('/'),
      next,
    )

    expect(next).toHaveBeenCalledWith()
  })

  it('redirects to /login when /api/auth/me fails on admin-only route', async () => {
    api.auth.me.mockRejectedValue({ response: { status: 401 } })

    await guard(
      makeRoute('/admin/users', { requiresAuth: true, requiresAdmin: true }),
      makeRoute('/'),
      next,
    )

    expect(next).toHaveBeenCalledWith({
      path: '/login',
      query: { redirect: '/admin/users' },
    })
  })

  describe('admin-panel edition gate (IMP-5042 ceOrTeamOnly)', () => {
    it('redirects a SaaS admin away from a ceOrTeamOnly route (Solo has no admin panel)', async () => {
      setupService.checkEnhancedStatus.mockResolvedValue({
        is_fresh_install: false,
        total_users_count: 2,
        route_signal: null,
        show_public_landing: false,
        mode: 'saas',
      })
      api.auth.me.mockResolvedValue({ data: { id: 2, username: 'root', role: 'admin' } })

      await guard(
        makeRoute('/admin/settings', {
          requiresAuth: true,
          requiresAdmin: true,
          ceOrTeamOnly: true,
        }),
        makeRoute('/'),
        next,
      )

      expect(next).toHaveBeenCalledWith({ name: 'Dashboard' })
    })

    it('allows a CE admin into a ceOrTeamOnly route (CE always keeps the admin panel)', async () => {
      // beforeEach default mode is 'ce'.
      api.auth.me.mockResolvedValue({ data: { id: 2, username: 'root', role: 'admin' } })

      await guard(
        makeRoute('/admin/settings', {
          requiresAuth: true,
          requiresAdmin: true,
          ceOrTeamOnly: true,
        }),
        makeRoute('/'),
        next,
      )

      expect(next).toHaveBeenCalledWith()
    })
  })

  describe('logout-then-navigate regression (the mcp.example.com bug)', () => {
    it('redirects to /login after logout when user types /home in address bar', async () => {
      const store = useUserStore()

      // Simulate successful logout state:
      // - store is cleared
      // - backend cookie is invalid so /api/auth/me returns 401
      store.currentUser = null
      api.auth.me.mockRejectedValue({ response: { status: 401 } })

      await guard(makeRoute('/home'), makeRoute('/'), next)

      expect(api.auth.me).toHaveBeenCalledTimes(1)
      expect(next).toHaveBeenCalledWith({
        path: '/login',
        query: { redirect: '/home' },
      })
    })

    it('redirects to /login for each protected route after logout (regression suite)', async () => {
      const protectedPaths = ['/home', '/projects', '/Dashboard', '/settings', '/tasks']
      api.auth.me.mockRejectedValue({ response: { status: 401 } })

      for (const p of protectedPaths) {
        next.mockClear()
        await guard(makeRoute(p), makeRoute('/'), next)
        expect(next).toHaveBeenCalledWith({
          path: '/login',
          query: { redirect: p },
        })
      }
    })
  })

  describe('demo public landing root visit', () => {
    beforeEach(() => {
      setupService.checkEnhancedStatus.mockResolvedValue({
        is_fresh_install: false,
        total_users_count: 2,
        route_signal: 'public_landing',
        show_public_landing: true,
        mode: 'demo',
      })
      configService.getGiljoMode.mockReturnValue('demo')
    })

    it('routes anonymous bare / visits to /landing after router rewrites / to /home', async () => {
      api.auth.me.mockRejectedValue({ response: { status: 401 } })

      await guard(makeRedirectedRoute('/home', '/'), makeRoute('/'), next)

      expect(api.auth.me).toHaveBeenCalledTimes(1)
      expect(next).toHaveBeenCalledWith('/landing')
    })

    it('still sends anonymous direct /home visits to login with redirect', async () => {
      api.auth.me.mockRejectedValue({ response: { status: 401 } })

      await guard(makeRoute('/home'), makeRoute('/'), next)

      expect(api.auth.me).toHaveBeenCalledTimes(1)
      expect(next).toHaveBeenCalledWith({
        path: '/login',
        query: { redirect: '/home' },
      })
    })
  })

  describe('public policy documents reachable while logged out', () => {
    // /privacy and /terms are public by definition -- a visitor must be able to
    // read them before signing up, and a directory reviewer or privacy
    // regulator will deep-link straight to them. Both are declared
    // `requiresAuth: false, layout: 'auth'` in the router, but PRIORITY 1 runs
    // ahead of the public-layout allowance and its exemption list omitted them,
    // so on a public_landing deployment an anonymous visitor was bounced to
    // /landing and never saw the document.
    beforeEach(() => {
      setupService.checkEnhancedStatus.mockResolvedValue({
        is_fresh_install: false,
        total_users_count: 4,
        route_signal: 'public_landing',
        show_public_landing: true,
        mode: 'saas',
      })
      configService.getGiljoMode.mockReturnValue('saas')
    })

    const policyRoute = (path) =>
      makeRoute(path, { requiresAuth: false, layout: 'auth', requiresSetup: false })

    it.each(['/privacy', '/terms'])(
      'renders %s for an anonymous visitor instead of redirecting to /landing',
      async (path) => {
        api.auth.me.mockRejectedValue({ response: { status: 401 } })

        await guard(policyRoute(path), makeRoute('/'), next)

        expect(next).toHaveBeenCalledWith()
      },
    )

    it('still sends an anonymous visitor to /landing for a non-policy public route', async () => {
      // The exemption is scoped to the two documents, not a blanket
      // public_landing bypass.
      api.auth.me.mockRejectedValue({ response: { status: 401 } })

      await guard(policyRoute('/some-other-public-page'), makeRoute('/'), next)

      expect(next).toHaveBeenCalledWith('/landing')
    })
  })
})
