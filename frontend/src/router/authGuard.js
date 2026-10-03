
import { useUserStore } from '@/stores/user'
import { PRODUCT_NAME } from '@/branding'
import { isCeModeValue } from '@/composables/useGiljoMode'

export function createAuthGuard({ setupService, configService }) {
  return async function authGuard(to, from, next) {
    document.title = `${to.meta?.title || 'GiljoAI'} - ${PRODUCT_NAME}`

    let setupState = null
    try {
      setupState = await setupService.checkEnhancedStatus()
    } catch {
      // Network error -- proceed with configService fallback below
    }

    const mode = (() => {
      if (setupState?.mode) return setupState.mode
      try {
        return configService.getGiljoMode()
      } catch {
        return 'ce'
      }
    })()
    const isPublicLandingMode = !isCeModeValue(mode)

    const userStore = useUserStore()
    const isAuthRouteLayout = to.meta?.layout === 'auth'
    const requiresAuth = to.meta?.requiresAuth !== false && !isAuthRouteLayout
    const isBareRootVisit = to.redirectedFrom?.path === '/'

    let isAuthenticated = !!userStore.currentUser
    if (requiresAuth) {
      try {
        isAuthenticated = await userStore.checkAuth()
      } catch {
        isAuthenticated = false
      }
    }

    if (
      setupState &&
      to.path !== '/welcome' &&
      to.path !== '/login' &&
      to.path !== '/landing' &&
      to.path !== '/register' &&
      to.path !== '/reset-password' &&
      to.path !== '/account/confirm-deletion' &&
      to.path !== '/account/cancel-deletion' &&
      to.path !== '/privacy' &&
      to.path !== '/terms'
    ) {
      const signal = setupState.route_signal
      const hasUsers = (setupState.total_users_count ?? 0) > 0

      if (signal === 'public_landing' && !isAuthenticated) {
        if (to.path.startsWith('/oauth/')) {
          next()
          return
        }
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
        next('/welcome')
        return
      }
    }

    if (isAuthRouteLayout) {
      if (to.path === '/welcome') {
        if (isPublicLandingMode) {
          console.warn('[SECURITY] Blocking /welcome in saas mode - admin bootstrap is CLI-only')
          next('/landing')
          return
        }
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

    if (requiresAuth && !isAuthenticated) {
      if (typeof userStore.clearUser === 'function') {
        userStore.clearUser()
      }
      next({
        path: '/login',
        query: { redirect: to.fullPath },
      })
      return
    }

    if (to.meta?.requiresAdmin && !userStore.isAdmin) {
      next({ name: 'Dashboard' })
      return
    }

    if (to.meta?.ceOrTeamOnly && !isCeModeValue(mode)) {
      next({ name: 'Dashboard' })
      return
    }

    next()
  }
}
