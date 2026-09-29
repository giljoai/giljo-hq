/**
 * Test suite for DefaultLayout component
 * TDD approach: Tests written BEFORE implementation
 *
 * DefaultLayout is the full application layout for app routes (dashboard, settings, etc.)
 * - Includes NavigationDrawer
 * - Loads user data on mount via userStore.fetchCurrentUser()
 * - Reloads user after navigation from login
 * - Passes currentUser to child components
 *
 * Post-refactor notes:
 * - DefaultLayout uses userStore.fetchCurrentUser() which internally calls api.auth.me()
 * - Fresh install check done via fetch() before loading user
 * - ToastManager and LicensingDialog added as global components
 * - WebSocket and websocketEventRouter initialized on mount
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import api from '@/services/api'

// Mock the API module
vi.mock('@/services/api', () => ({
  default: {
    auth: {
      me: vi.fn()
    }
  }
}))

// Mock child components
vi.mock('@/components/navigation/NavigationDrawer.vue', () => ({
  default: {
    name: 'NavigationDrawer',
    template: '<div>NavigationDrawer</div>',
    props: ['modelValue', 'rail', 'currentUser'],
    emits: ['update:modelValue', 'toggle-rail'],
  }
}))

vi.mock('@/components/ToastManager.vue', () => ({
  default: { name: 'ToastManager', template: '<div>ToastManager</div>' }
}))

vi.mock('@/components/LicensingDialog.vue', () => ({
  __esModule: true,
  default: { name: 'LicensingDialog', template: '<div>LicensingDialog</div>', __isTeleport: false, __isSuspense: false }
}))

// Mock stores and services
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    connect: vi.fn().mockResolvedValue(),
    disconnect: vi.fn(),
  })
}))

vi.mock('@/stores/websocketEventRouter', () => ({
  initWebsocketEventRouter: vi.fn(),
  // FE-3007b: DefaultLayout registers global reconnect resyncs; return an
  // unregister fn so onUnmounted cleanup does not throw.
  registerReconnectResync: vi.fn(() => vi.fn()),
}))

// FE-3007b: DefaultLayout imports the project store for the projects resync
// registration (only invoked on reconnect, never at mount).
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    fetchProjects: vi.fn().mockResolvedValue(),
  }),
}))

// Mock global fetch for setup status check
const mockFetch = vi.fn()
global.fetch = mockFetch

describe('DefaultLayout.vue', () => {
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

    // Create router with test routes
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/',
          name: 'dashboard',
          component: { template: '<div>Dashboard</div>' },
          meta: { layout: 'default', requiresAuth: true }
        },
        {
          path: '/login',
          name: 'login',
          component: { template: '<div>Login</div>' },
          meta: { layout: 'auth', requiresAuth: false }
        }
      ]
    })

    // Default: fresh install check returns non-fresh install
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ is_fresh_install: false }),
    })
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
    vi.clearAllMocks()
  })

  describe('Component Rendering', () => {
    it('should render without errors', async () => {
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia]
        }
      })

      await flushPromises()
      expect(wrapper.exists()).toBe(true)
    })

    it('should render v-app wrapper', async () => {
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia]
        }
      })

      await flushPromises()
      // Global test setup stubs v-app as <div class="v-app">
      const vApp = wrapper.find('.v-app')
      expect(vApp.exists()).toBe(true)
    })

    it('should render NavigationDrawer as the primary navigation component', async () => {
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })
      expect(navDrawer.exists()).toBe(true)
    })

    it('should render NavigationDrawer component', async () => {
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })
      expect(navDrawer.exists()).toBe(true)
    })

    it('should render router-view', async () => {
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      // Global test setup stubs v-main as <div class="v-main">
      const vMain = wrapper.find('.v-main')
      expect(vMain.exists()).toBe(true)
    })
  })

  describe('User Data Loading', () => {
    it('should load user data on mount via userStore.fetchCurrentUser', async () => {
      const mockUser = { username: 'admin', role: 'admin' }
      api.auth.me.mockResolvedValue({ data: mockUser })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      // api.auth.me is called by userStore.fetchCurrentUser
      expect(api.auth.me).toHaveBeenCalled()
      expect(wrapper.vm.currentUser).toEqual(mockUser)
    })

    it('should set currentUser ref after successful fetch', async () => {
      const mockUser = { username: 'testuser', role: 'developer' }
      api.auth.me.mockResolvedValue({ data: mockUser })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      expect(wrapper.vm.currentUser).toEqual(mockUser)
    })

    it('should handle API errors gracefully', async () => {
      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      expect(wrapper.vm.currentUser).toBeNull()
    })

    it('should redirect to login on auth failure', async () => {
      const pushSpy = vi.spyOn(router, 'push')
      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      expect(pushSpy).toHaveBeenCalledWith('/login')
    })
  })

  describe('Props Passing', () => {
    it('should pass currentUser to NavigationDrawer component', async () => {
      const mockUser = { username: 'admin', role: 'admin' }
      api.auth.me.mockResolvedValue({ data: mockUser })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })
      expect(navDrawer.props('currentUser')).toEqual(mockUser)
    })

    it('should pass currentUser to NavigationDrawer component', async () => {
      const mockUser = { username: 'admin', role: 'admin' }
      api.auth.me.mockResolvedValue({ data: mockUser })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })
      expect(navDrawer.props('currentUser')).toEqual(mockUser)
    })
  })

  describe('Route Meta Handling', () => {
    it('should hide NavigationDrawer when route meta hideDrawer is true', async () => {
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      // Update router with route that has hideDrawer meta
      router.addRoute({
        path: '/minimal',
        name: 'minimal',
        component: { template: '<div>Minimal</div>' },
        meta: { layout: 'default', hideDrawer: true }
      })

      await router.push('/minimal')

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })
      expect(navDrawer.exists()).toBe(false)
    })
  })

  describe('Drawer State Management', () => {
    const originalInnerWidth = window.innerWidth
    afterEach(() => {
      window.innerWidth = originalInnerWidth
    })

    it('should initialize drawer as open on a desktop-width window', async () => {
      window.innerWidth = 1280
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      expect(wrapper.vm.drawer).toBe(true)
    })

    it('FE-9648: starts with the overlay drawer closed on a narrow (1000px) desktop window', async () => {
      window.innerWidth = 1000
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()
      expect(wrapper.vm.drawer).toBe(false)
    })

    it('should toggle rail when NavigationDrawer emits toggle-rail event', async () => {
      api.auth.me.mockResolvedValue({
        data: { username: 'admin', role: 'admin' }
      })

      wrapper = mount(DefaultLayout, {
        global: {
          plugins: [vuetify, router, pinia],
        }
      })

      await flushPromises()

      const initialRailState = wrapper.vm.rail
      const navDrawer = wrapper.findComponent({ name: 'NavigationDrawer' })
      await navDrawer.vm.$emit('toggle-rail')
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.rail).toBe(!initialRailState)
    })
  })
})
