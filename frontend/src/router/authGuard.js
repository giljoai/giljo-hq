/**
 * Auth Guard Factory for vue-router's beforeEach hook.
 *
 * Extracted from router/index.js so the full navigation-guard flow can be
 * unit-tested in isolation (see tests/unit/router/authGuard.spec.js).
 *
 * Option A (per orchestrator mission 2026-04-24): every navigation to a
 * protected route re-verifies the session by calling /api/auth/me. On
 * auth failure the user store is fully reset and the user is redirected
 * to /login. This closes the route-guard-bypass leak observed on the demo
 * server where typing a URL into the address bar after logout rendered
 * the protected view without re-checking the backend.
 *
 * The factory takes its collaborators (setupService, configService) as
 * arguments so tests can supply mocks without module-mocking plumbing.
 */

import { useUserStore } from '@/stores/user'
import { PRODUCT_NAME } from '@/branding'

export function createAuthGuard({ setupService, configService }) {
  return async function authGuard(to, from, next) {
    // Set page title
    document.title = `${to.meta?.title || 'GiljoAI'} - ${PRODUCT_NAME}`

    // Fetch setupState ONCE at guard entry -- single source of truth for both
    // mode resolution and route_signal. setupService caches with a 2s TTL so
    // subsequent reads in the same navigation are free.
    let setupState = null
    try {
      setupState = await setupService.checkEnhancedStatus()
    } catch {
      // Network error -- proceed with configService fallback below
    }

    const mode = (() => {
      if (setupState?.mode) return setupState.mode
      // ADR-002 fallback: only fires when setupService.checkEnhancedStatus()
      // is unreachable (network error above). The authoritative source is
      // always setupState.mode; configService.getGiljoMode() can race on
      // first paint and defaults to 'ce', so it's the last-resort path.
      try {
        return configService.getGiljoMode()
      } catch {
        return 'ce'
      }
    })()
    // eslint-disable-next-line giljo-internal/no-scattered-mode-checks -- ADR-002: guard reads mode from setupState (not composable); non-component factory function cannot use Vue composable
    const isPublicLandingMode = mode !== 'ce'

    const userStore = useUserStore()
    const isAuthRouteLayout = to.meta?.layout === 'auth'
    const requiresAuth = to.meta?.requiresAuth !== false && !isAuthRouteLayout
    const isBareRootVisit = to.redirectedFrom?.path === '/'

    // Option A: re-verify the session with the backend on EVERY navigation
    // to a protected route. Do this exactly once per navigation and reuse
    // the result for both PRIORITY 1 (public-landing detection needs to
    // know whether the visitor is authenticated) and PRIORITY 3 (auth gate).
    //
    // For public-layout routes (login, welcome, landing, etc.) we only
    // peek at the store to decide landing routing; we do NOT call checkAuth
    // there because the page is public by design.
    let isAuthenticated = !!userStore.currentUser
    if (requiresAuth) {
      try {
        isAuthenticated = await userStore.checkAuth()
      } catch {
        isAuthenticated = false
      }
    }

    // PRIORITY 1: Fresh install / landing detection.
    // Skip for the landing targets themselves and for /login to avoid loops.
    if (
      setupState &&
      to.path !== '/welcome' &&
      to.path !== '/login' &&
      to.path !== '/landing' &&
      to.path !== '/register' &&
      to.path !== '/reset-password' &&
      to.path !== '/account/confirm-deletion' &&
      to.path !== '/account/cancel-deletion'
    ) {
      const signal = setupState.route_signal
      // Only preserve deep-links to /login when users actually exist. On a
      // fresh install (total_users_count === 0) /login is a dead-end -- the
      // landing page is the only sensible destination.
      const hasUsers = (setupState.total_users_count ?? 0) > 0

      if (signal === 'public_landing' && !isAuthenticated) {
        // API-0021d Phase 1: OAuth Authorization Code flow exemption.
        // claude.ai (and other MCP clients) deep-link anonymous users to
        // /oauth/authorize with critical query params (client_id,
        // redirect_uri, state, code_challenge). The OAuth view owns its own
        // unauthenticated UX (inline login that preserves the OAuth params),
        // so the public-landing redirect must NOT hijack /oauth/* paths -
        // doing so strips the params and breaks the handshake. Path-prefix
        // matching (not exact /oauth/authorize) defends against re-navigation
        // mid-flow (e.g. /oauth/callback, /oauth/authorize/, etc.).
        // Conditional on signal === 'public_landing' so CE behavior is
        // unchanged (CE never emits that signal).
        if (to.path.startsWith('/oauth/')) {
          // Skip PRIORITY-1 entirely for OAuth paths and let PRIORITY-2/3
          // handle the request (the OAuth view itself owns its auth UX).
          next()
          return
        }
        // Deep-link preserving: a logged-out user clicking a bookmark like
        // /home or /projects should land on /login with ?redirect= so they
        // return to the bookmarked page after signing in. Vue Router rewrites
        // bare "/" visits to "/home"; treat redirectedFrom="/" as the public
        // landing visit, not as a protected deep link.
        if (requiresAuth && !isBareRootVisit && hasUsers) {
          next({ path: '/login', query: { redirect: to.fullPath } })
        } else {
          next('/landing')
        }
        return
      }
      if (signal === 'create_admin') {
        next('/welcome')
        return
      }
      // Legacy / belt-and-suspenders path (no route_signal yet or transient error).
      // In demo/saas we NEVER want the CreateAdminAccount wizard to be visible.
      if (
        isPublicLandingMode &&
        !isAuthenticated &&
        (setupState.show_public_landing || setupState.is_fresh_install)
      ) {
        if (requiresAuth && !isBareRootVisit && hasUsers) {
          next({ path: '/login', query: { redirect: to.fullPath } })
        } else {
          next('/landing')
        }
        return
      }

      if (!isPublicLandingMode && setupState.is_fresh_install) {
        // CE fresh install (0 users) - redirect to create admin account
        next('/welcome')
        return
      }
    }

    // PRIORITY 2: Auth routes (layout: 'auth') - allow access without authentication.
    if (isAuthRouteLayout) {
      // Security check: Block /welcome if users exist OR if we're in demo/saas mode
      // (demo/saas must never expose the admin-bootstrap UI publicly).
      if (to.path === '/welcome') {
        if (isPublicLandingMode) {
          console.warn('[SECURITY] Blocking /welcome in saas mode - admin bootstrap is CLI-only')
          next('/landing')
          return
        }
        // CE: block /welcome only when users genuinely exist.
        if (setupState && !setupState.is_fresh_install && (setupState.total_users_count ?? 0) > 0) {
          console.warn(
            '[SECURITY] Blocking /welcome access - users exist (total:',
            setupState.total_users_count,
            ')',
          )
          next('/login')
          return
        }
      }
      next()
      return
    }

    // PRIORITY 3: App routes (layout: 'default') - enforce the auth check
    // we already performed above. On failure, fully reset the auth store
    // (so no component can render based on stale currentUser/orgId) and
    // redirect to /login with a redirect query param so the user lands
    // back where they were after re-authenticating.
    if (requiresAuth && !isAuthenticated) {
      // Defence-in-depth: checkAuth() already clears user + org state on
      // failure, but call clearUser() explicitly in case a future change
      // to the store action forgets it.
      if (typeof userStore.clearUser === 'function') {
        userStore.clearUser()
      }
      next({
        path: '/login',
        query: { redirect: to.fullPath },
      })
      return
    }

    // Check admin role requirement
    if (to.meta?.requiresAdmin && !userStore.isAdmin) {
      next({ name: 'Dashboard' })
      return
    }

    // IMP-5042: the admin panel (workspace + user management) is gated to editions
    // that support multi-user administration. CE always has it (self-hosted
    // operator surface); SaaS exposes it only once a Team tier ships. Today no
    // SaaS edition does, so SaaS users hitting /admin/* are redirected to their
    // dashboard. `mode` is resolved from setupState above (ADR-002). When Team
    // ships, relax this to also allow SaaS Team admins.
    // The guard must read mode from setupState (documented contract above); it
    // cannot use the useSaasMode/useEditionCapabilities funnel (reads configService).
    // eslint-disable-next-line giljo-internal/no-scattered-mode-checks
    if (to.meta?.ceOrTeamOnly && mode !== 'ce') {
      next({ name: 'Dashboard' })
      return
    }

    // All checks passed, allow navigation
    next()
  }
}
