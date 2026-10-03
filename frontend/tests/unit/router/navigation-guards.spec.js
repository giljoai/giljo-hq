/**
 * Unit tests for router navigation guards - role-based access control
 * Tests that routes with requiresAdmin meta property are protected
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '@/stores/user'

// Mock the API service
vi.mock('@/services/api', () => ({
  default: {
    auth: {
      me: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
    },
  },
}))

// Mock setup service
vi.mock('@/services/setupService', () => ({
  default: {
  },
}))

describe('Router Navigation Guards - Role-based Access', () => {
  let router
  let userStore

  beforeEach(async () => {
    // Create a fresh pinia instance
    setActivePinia(createPinia())
    userStore = useUserStore()

    // Create router with test routes
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/',
          name: 'Dashboard',
          component: { template: '<div>Dashboard</div>' },
          meta: { requiresAuth: true },
        },
        {
          path: '/login',
          name: 'Login',
          component: { template: '<div>Login</div>' },
          meta: { requiresAuth: false, requiresSetup: false },
        },
        {
          path: '/users',
          name: 'Users',
          component: { template: '<div>Users</div>' },
          meta: { requiresAuth: true, requiresAdmin: true },
        },
        {
          path: '/settings',
          name: 'Settings',
          component: { template: '<div>Settings</div>' },
          meta: { requiresAuth: true },
        },
      ],
    })

    // Add navigation guard
    router.beforeEach((to, from, next) => {
      // Skip auth checks for routes that explicitly don't require them
      if (to.meta.requiresAuth === false) {
        next()
        return
      }

      // Check authentication
      if (to.meta.requiresAuth && !userStore.isAuthenticated) {
        next({ name: 'Login', query: { redirect: to.fullPath } })
        return
      }

      // Check admin role
      if (to.meta.requiresAdmin && !userStore.isAdmin) {
        next({ name: 'Dashboard' })
        return
      }

      next()
    })
  })

  describe('Authentication Guard', () => {
    it('should allow unauthenticated users to access login page', async () => {
      await router.push('/login')
      expect(router.currentRoute.value.name).toBe('Login')
    })

    it('should redirect unauthenticated users from protected routes to login', async () => {
      await router.push('/')
      expect(router.currentRoute.value.name).toBe('Login')
      expect(router.currentRoute.value.query.redirect).toBe('/')
    })

    it('should allow authenticated users to access protected routes', async () => {
      // Set authenticated user
      userStore.currentUser = { username: 'testuser', role: 'user' }

      await router.push('/')
      expect(router.currentRoute.value.name).toBe('Dashboard')
    })
  })

  describe('Admin Role Guard', () => {
    it('should block non-admin users from admin-only routes', async () => {
      // Set regular user
      userStore.currentUser = { username: 'testuser', role: 'user' }

      await router.push('/users')
      expect(router.currentRoute.value.name).toBe('Dashboard')
    })

    it('should allow admin users to access admin-only routes', async () => {
      // Set admin user
      userStore.currentUser = { username: 'admin', role: 'admin' }

      await router.push('/users')
      expect(router.currentRoute.value.name).toBe('Users')
    })

    it('should redirect unauthenticated users trying to access admin routes to login', async () => {
      await router.push('/users')
      expect(router.currentRoute.value.name).toBe('Login')
    })

    it('should handle case-insensitive admin role', async () => {
      // Set admin user with different case
      userStore.currentUser = { username: 'admin', role: 'Admin' }

      await router.push('/users')
      expect(router.currentRoute.value.name).toBe('Users')
    })
  })

  describe('Navigation Flow', () => {
    it('should preserve redirect query param when redirecting to login', async () => {
      await router.push('/users')

      expect(router.currentRoute.value.name).toBe('Login')
      expect(router.currentRoute.value.query.redirect).toBe('/users')
    })

    it('should allow admin to access all routes', async () => {
      userStore.currentUser = { username: 'admin', role: 'admin' }

      // Test navigation to all routes
      await router.push('/')
      expect(router.currentRoute.value.name).toBe('Dashboard')

      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('Settings')

      await router.push('/users')
      expect(router.currentRoute.value.name).toBe('Users')
    })

    it('should restrict regular user from admin routes only', async () => {
      userStore.currentUser = { username: 'testuser', role: 'user' }

      // Can access regular routes
      await router.push('/')
      expect(router.currentRoute.value.name).toBe('Dashboard')

      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('Settings')

      // Cannot access admin routes
      await router.push('/users')
      expect(router.currentRoute.value.name).toBe('Dashboard')
    })
  })

  describe('Edge Cases', () => {
    it('should handle user with no role as non-admin', async () => {
      userStore.currentUser = { username: 'testuser' }

      await router.push('/users')
      expect(router.currentRoute.value.name).toBe('Dashboard')
    })

    it('should handle null user as unauthenticated', async () => {
      userStore.currentUser = null

      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('Login')
    })
  })
})
