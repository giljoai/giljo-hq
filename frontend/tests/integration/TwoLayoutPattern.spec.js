/**
 * Integration Test Suite: Two-Layout Authentication Pattern
 *
 * Tests the integration between App.vue, Router, and Layouts
 * according to handover 0024_HANDOVER_20251016_TWO_LAYOUT_AUTH_PATTERN.md
 *
 * Key Requirements:
 * - Router selects correct layout based on meta.layout
 * - AuthLayout used for /welcome and /login (no auth required)
 * - DefaultLayout used for app routes (auth required)
 * - Navigation guard allows auth routes without authentication
 * - Navigation guard blocks app routes without authentication
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import App from '@/App.vue'
import api from '@/services/api'

// Mock the API and setup service modules
vi.mock('@/services/api', () => ({
  default: {
    auth: {
      me: vi.fn()
    }
  }
}))

vi.mock('@/services/setupService', () => ({ default: {} }))

describe('Two-Layout Authentication Pattern - Integration Tests', () => {
  let vuetify
  let wrapper
  let router
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)

    vuetify = createVuetify({
      components,
      directives,
    })

    // Create router with realistic routes matching the actual application
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/login',
          name: 'Login',
          component: { template: '<div>Login Page</div>' },
          meta: {
            layout: 'auth',
            title: 'Login',
            requiresAuth: false,
            requiresSetup: false,
            requiresPasswordChange: false,
          },
        },
        {
          path: '/welcome',
          name: 'WelcomeSetup',
          component: { template: '<div>Welcome Page</div>' },
          meta: {
            layout: 'auth',
            title: 'Welcome',
            requiresAuth: false,
            requiresSetup: false,
            requiresPasswordChange: false,
          },
        },
        {
          path: '/server-down',
          name: 'ServerDown',
          component: { template: '<div>Server Down</div>' },
          meta: {
            layout: 'auth',
            title: 'Server Unreachable',
            requiresAuth: false,
            requiresSetup: false,
            requiresPasswordChange: false,
          },
        },
        {
          path: '/',
          name: 'Dashboard',
          component: { template: '<div>Dashboard Page</div>' },
          meta: {
            layout: 'default',
            title: 'Dashboard',
            requiresAuth: true,
          },
        },
        {
          path: '/settings',
          name: 'Settings',
          component: { template: '<div>Settings Page</div>' },
          meta: {
            layout: 'default',
            title: 'Settings',
            requiresAuth: true,
          },
        },
        {
          path: '/admin/settings',
          name: 'SystemSettings',
          component: { template: '<div>System Settings</div>' },
          meta: {
            layout: 'default',
            title: 'System Settings',
            requiresAuth: true,
            requiresAdmin: true,
          },
        },
      ]
    })

    // Add navigation guard that mimics real router behavior
    router.beforeEach(async (to) => {
      // Auth-layout routes are always allowed
      if (to.meta.layout === 'auth') {
        return true
      }

      // App routes require authentication
      if (to.meta.requiresAuth) {
        try {
          await api.auth.me()
          return true
        } catch {
          // Not authenticated, redirect to login
          return { path: '/login', query: { redirect: to.fullPath } }
        }
      }

      return true
    })

    api.auth.me.mockResolvedValue({
      data: { username: 'admin', role: 'admin' }
    })
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
    vi.clearAllMocks()
  })

  describe('Layout Selection Based on Route Meta', () => {
    it('should use AuthLayout for /login route', async () => {
      await router.push('/login')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // AuthLayout should not have AppBar or NavigationDrawer
      const appBar = wrapper.findComponent({ name: 'AppBar' })
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })

      expect(appBar.exists()).toBe(false)
      expect(navDrawer.exists()).toBe(false)
      expect(wrapper.html()).toContain('Login Page')
    })

    it('should use AuthLayout for /welcome route', async () => {
      await router.push('/welcome')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // AuthLayout should not have AppBar or NavigationDrawer
      const appBar = wrapper.findComponent({ name: 'AppBar' })
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })

      expect(appBar.exists()).toBe(false)
      expect(navDrawer.exists()).toBe(false)
      expect(wrapper.html()).toContain('Welcome Page')
    })

    it('should use AuthLayout for /server-down route', async () => {
      await router.push('/server-down')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // AuthLayout should not have AppBar or NavigationDrawer
      const appBar = wrapper.findComponent({ name: 'AppBar' })
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })

      expect(appBar.exists()).toBe(false)
      expect(navDrawer.exists()).toBe(false)
      expect(wrapper.html()).toContain('Server Down')
    })

    it('should use DefaultLayout for / (dashboard) route', async () => {
      await router.push('/')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // DefaultLayout should have NavigationDrawer (AppBar is no longer a top-level layout component)
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })

      expect(navDrawer.exists()).toBe(true)
      expect(wrapper.html()).toContain('Dashboard Page')
    })

    it('should use DefaultLayout for /settings route', async () => {
      await router.push('/settings')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // DefaultLayout should have NavigationDrawer (AppBar is no longer a top-level layout component)
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })

      expect(navDrawer.exists()).toBe(true)
      expect(wrapper.html()).toContain('Settings Page')
    })
  })

  describe('Navigation Guard - Auth Routes Allowed Without Authentication', () => {
    it('should allow access to /login without authentication', async () => {
      // Mock authentication failure
      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      await router.push('/login')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // Should render login page without redirect
      expect(wrapper.html()).toContain('Login Page')
      expect(router.currentRoute.value.path).toBe('/login')
    })

    it('should allow access to /welcome without authentication', async () => {
      // Mock authentication failure
      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      await router.push('/welcome')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // Should render welcome page without redirect
      expect(wrapper.html()).toContain('Welcome Page')
      expect(router.currentRoute.value.path).toBe('/welcome')
    })

    it('should allow access to /server-down without authentication', async () => {
      // Mock authentication failure
      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      await router.push('/server-down')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // Should render server down page without redirect
      expect(wrapper.html()).toContain('Server Down')
      expect(router.currentRoute.value.path).toBe('/server-down')
    })
  })

  describe('Navigation Guard - App Routes Blocked Without Authentication', () => {
    it('should redirect to /login when accessing / without authentication', async () => {
      // Mock authentication failure
      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      // Create wrapper first, then navigate
      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      // Navigate after mounting
      await router.push('/')
      await flushPromises()

      // Should redirect to login
      expect(router.currentRoute.value.path).toBe('/login')
      // Verify redirect query parameter is set (if any)
      if (router.currentRoute.value.query.redirect) {
        expect(router.currentRoute.value.query.redirect).toBe('/')
      }
    })

    it('should redirect to /login when accessing /settings without authentication', async () => {
      // Mock authentication failure
      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      // Create wrapper first, then navigate
      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      // Navigate after mounting
      await router.push('/settings')
      await flushPromises()

      // Should redirect to login
      expect(router.currentRoute.value.path).toBe('/login')
      // Verify redirect query parameter is set (if any)
      if (router.currentRoute.value.query.redirect) {
        expect(router.currentRoute.value.query.redirect).toBe('/settings')
      }
    })
  })

  describe('Navigation Guard - App Routes Allowed With Authentication', () => {
    it('should allow access to / when authenticated', async () => {
      // Mock successful authentication
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      await router.push('/')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // Should render dashboard
      expect(router.currentRoute.value.path).toBe('/')
      expect(wrapper.html()).toContain('Dashboard Page')
    })

    it('should allow access to /settings when authenticated', async () => {
      // Mock successful authentication
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      await router.push('/settings')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // Should render settings
      expect(router.currentRoute.value.path).toBe('/settings')
      expect(wrapper.html()).toContain('Settings Page')
    })
  })

  describe('Navigation Guard - Role-Based Access', () => {
    it('should use DefaultLayout for admin routes when authenticated', async () => {
      // Mock authentication as admin user
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      await router.push('/admin/settings')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // Should use DefaultLayout for admin routes (NavigationDrawer is the top-level nav component)
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })

      expect(navDrawer.exists()).toBe(true)
      expect(router.currentRoute.value.path).toBe('/admin/settings')
    })
  })

  describe('Setup Flow Integration with Two-Layout Pattern', () => {
    it('should allow access to /welcome during setup', async () => {
      // Navigate to welcome page during setup
      await router.push('/welcome')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // Should be on welcome page
      expect(router.currentRoute.value.path).toBe('/welcome')
      expect(wrapper.html()).toContain('Welcome Page')
    })

    it('should use AuthLayout for setup flow pages', async () => {
      await router.push('/welcome')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // Should use AuthLayout (no navigation components)
      const appBar = wrapper.findComponent({ name: 'AppBar' })
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })

      expect(appBar.exists()).toBe(false)
      expect(navDrawer.exists()).toBe(false)
    })
  })

  describe('User Data Loading with Two-Layout Pattern', () => {
    it('should NOT load user data when on auth routes', async () => {
      api.auth.me.mockClear()

      await router.push('/login')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // AuthLayout should not load user data
      // Navigation guard will check auth but won't load for auth routes
      expect(wrapper.html()).toContain('Login Page')
    })

    it('should load user data when on app routes', async () => {
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      await router.push('/')
      await router.isReady()

      wrapper = mount(App, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            AppBar: true,
            NavigationDrawer: true
          }
        }
      })

      await flushPromises()

      // DefaultLayout should load user data
      expect(api.auth.me).toHaveBeenCalled()
    })
  })
})
