/**
 * Test suite for SystemSettings.vue component
 *
 * Tests the System Settings view functionality including:
 * - Network configuration (external host, API port, CORS)
 * - Database settings (readonly display)
 * - Security configuration (cookie domain whitelist)
 * - System settings (orchestrator prompt override)
 * - Admin-only access
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { createPinia, setActivePinia } from 'pinia'
import SystemSettings from '@/views/SystemSettings.vue'
import configService from '@/services/configService'

// Mock the api service
// FE-9553: local hoisted toast spy -- see the same note in the RoadmapView and
// ApiKeyManager specs. The global mock in tests/setup.js hands out a fresh
// vi.fn() per call, so a toast assertion through it observes nothing.
const showToastSpy = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastSpy }),
}))

vi.mock('@/services/api', () => ({
  default: {
    settings: {
      getCookieDomains: vi.fn().mockResolvedValue({ data: { domains: [] } }),
      addCookieDomain: vi.fn().mockResolvedValue({ data: { success: true } }),
      removeCookieDomain: vi.fn().mockResolvedValue({ data: { success: true } }),
    },
    system: {
      getOrchestratorPrompt: vi
        .fn()
        .mockResolvedValue({ data: { content: 'test prompt', is_override: false } }),
      updateOrchestratorPrompt: vi
        .fn()
        .mockResolvedValue({ data: { content: 'updated', is_override: true } }),
      resetOrchestratorPrompt: vi
        .fn()
        .mockResolvedValue({ data: { content: 'default', is_override: false } }),
    },
  },
}))

describe('SystemSettings.vue', () => {
  let vuetify
  let router
  let pinia
  let wrapper

  beforeEach(() => {
    // FE-6055: getGiljoMode() now resolves to 'unknown' (not 'ce') without a
    // real config, and the CE-only settings tabs gate on a confirmed 'ce'. This
    // suite exercises the CE network/database/security tabs, so seed a
    // confirmed-CE config.
    configService.config = { giljo_mode: 'ce', mode: 'server', api: {} }

    // Setup Vuetify
    vuetify = createVuetify({
      components,
      directives,
    })

    // Setup Pinia
    pinia = createPinia()
    setActivePinia(pinia)

    // Setup Router
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'Dashboard', component: { template: '<div>Dashboard</div>' } },
        { path: '/admin/settings', name: 'SystemSettings', component: SystemSettings },
        // NetworkSettingsTab links to the user guide for cert setup (FE-6239).
        { path: '/guide', name: 'UserGuide', component: { template: '<div>Guide</div>' } },
      ],
    })

    // Mock fetch - provide default responses for onMounted calls
    global.fetch = vi.fn().mockImplementation((url) => {
      // Default response for database config
      if (url.includes('/api/v1/config/database')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ database: { host: 'localhost', port: 5432 } }),
        })
      }
      // Network info (the responding Host IP(s) + Port) — FE-6239.
      if (url.includes('/api/v1/config/network-info')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ hosts: ['localhost'], host_display: 'localhost', port: 7272, bind_all: false }),
        })
      }
      // Default response for network config (ssl_enabled fallback)
      if (url.includes('/api/v1/config')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            services: { api: { port: 7272 } },
            features: { ssl_enabled: false },
          }),
        })
      }
      // Default response for cookie domains
      if (url.includes('/api/settings/cookie-domains')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ domains: [] }),
        })
      }
      return Promise.reject(new Error('Unmocked fetch'))
    })
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
    vi.clearAllMocks()
    configService.clearCache()
  })

  describe('Component Rendering', () => {
    it('renders the component', () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
          },
        },
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('displays page title "Admin Settings"', () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })

      expect(wrapper.text()).toContain('Admin Settings')
    })

    it('displays admin-only subtitle', () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
          },
        },
      })

      expect(wrapper.text()).toContain('Configure server and system-wide settings')
      expect(wrapper.text()).toContain('Admin only')
    })
  })

  describe('Tab Navigation', () => {
    const defaultStubs = {
      DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
      NetworkSettingsTab: { template: '<div>Network Tab</div>' },
      SystemPromptTab: { template: '<div>System Tab</div>' },
    }

    // FE-6245: Security tab retired; Cookie Domain Whitelist moved to Network tab.
    it('renders 3 CE tabs (Identity, Network, Database) — Security tab retired', () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: defaultStubs,
        },
      })

      const text = wrapper.text()
      expect(text).toContain('Identity')
      expect(text).toContain('Network')
      expect(text).toContain('Database')
      // Security tab is gone — Cookie Whitelist now lives in the Network tab
      expect(wrapper.find('[data-test="security-tab"]').exists()).toBe(false)
      // IMP-5042: Prompts tab relocated to Account -> Danger Zone.
      expect(text).not.toContain('Prompts')
    })

    it('renders Network tab', () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: defaultStubs,
        },
      })

      expect(wrapper.text()).toContain('Network')
    })

    it('renders Database tab', () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: defaultStubs,
        },
      })

      expect(wrapper.text()).toContain('Database')
    })

    // IMP-5042: the Prompts/orchestrator tab moved to Account -> Danger Zone,
    // so it is no longer rendered by the admin SystemSettings view.
    it('does NOT render the Prompts tab', () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: defaultStubs,
        },
      })

      expect(wrapper.find('[data-test="prompts-tab"]').exists()).toBe(false)
    })
  })

  describe('Network Tab - Refactored v3.1', () => {
    const mockNetworkInfo = (hostDisplay, port) => {
      global.fetch.mockImplementation((url) => {
        if (url.includes('/api/v1/config/database')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ database: { host: 'localhost', port: 5432 } }),
          })
        }
        if (url.includes('/api/v1/config/network-info')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ hosts: [hostDisplay], host_display: hostDisplay, port, bind_all: true }),
          })
        }
        if (url.includes('/api/v1/config')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ services: { api: { port } }, features: { ssl_enabled: false } }),
          })
        }
        if (url.includes('/api/settings/cookie-domains')) {
          return Promise.resolve({ ok: true, json: async () => ({ domains: [] }) })
        }
        return Promise.reject(new Error('Unmocked fetch'))
      })
    }

    it('displays the real responding Host IP from network-info', async () => {
      mockNetworkInfo('192.0.2.100', 7272)

      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })

      await wrapper.vm.$nextTick()
      await new Promise((resolve) => setTimeout(resolve, 0))

      expect(wrapper.vm.serverHostDisplay).toBe('192.0.2.100')
    })

    it('displays the server Port from network-info', async () => {
      mockNetworkInfo('localhost', 7272)

      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })

      await wrapper.vm.$nextTick()
      await new Promise((resolve) => setTimeout(resolve, 0))

      expect(wrapper.vm.serverPort).toBe(7272)
    })

    it('renders NetworkSettingsTab component with correct props', async () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
            NetworkSettingsTab: {
              template: '<div data-test="network-settings-tab">Network Tab</div>',
              props: ['serverHostDisplay', 'serverPort', 'sslEnabled', 'loading'],
            },

            SystemPromptTab: { template: '<div>System Tab</div>' },
          },
        },
      })

      const networkTab = wrapper.find('[data-test="network-settings-tab"]')
      expect(networkTab.exists()).toBe(true)
    })

    it('passes the resolved host + port to NetworkSettingsTab', async () => {
      mockNetworkInfo('192.0.2.100', 7272)

      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
            NetworkSettingsTab: { template: '<div>Network Tab</div>' },

            SystemPromptTab: { template: '<div>System Tab</div>' },
          },
        },
      })

      await wrapper.vm.$nextTick()
      await new Promise((resolve) => setTimeout(resolve, 0))

      expect(wrapper.vm.serverHostDisplay).toBe('192.0.2.100')
      expect(wrapper.vm.serverPort).toBe(7272)
    })

    it('does NOT show deprecated mode chip', async () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })

      const modeChip = wrapper.find('[data-test="mode-chip"]')
      expect(modeChip.exists()).toBe(false)
    })

    it('does NOT show deprecated API key info', async () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })

      const apiKeyField = wrapper.find('[data-test="api-key-field"]')
      expect(apiKeyField.exists()).toBe(false)
    })

    it('does NOT show regenerate API key button', async () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })

      const regenerateBtn = wrapper.find('[data-test="regenerate-api-key-btn"]')
      expect(regenerateBtn.exists()).toBe(false)
    })

    it('falls back to default values when config fails to load', async () => {
      global.fetch.mockRejectedValueOnce(new Error('Network error'))

      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })

      await wrapper.vm.$nextTick()
      await new Promise((resolve) => setTimeout(resolve, 0))

      // On failure, fall back to the address this client reached the server on.
      expect(wrapper.vm.serverHostDisplay).toBe('localhost')
      expect(wrapper.vm.serverPort).toBe(7272)
    })

    it('renders child component tabs correctly', async () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
            NetworkSettingsTab: { template: '<div data-test="network-stub">Network</div>' },

            SystemPromptTab: { template: '<div data-test="system-stub">System</div>' },
          },
        },
      })

      // Network tab is default, should be visible
      const networkStub = wrapper.find('[data-test="network-stub"]')
      expect(networkStub.exists()).toBe(true)
    })
  })

  describe('Database Tab', () => {
    it('renders DatabaseConnection component', async () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: {
              template: '<div data-test="database-connection-stub">Database Connection Mock</div>',
            },
          },
        },
      })

      if (wrapper.vm.activeTab !== undefined) {
        wrapper.vm.activeTab = 'database'
        await wrapper.vm.$nextTick()
      }

      const dbConnection = wrapper.find('[data-test="database-connection-stub"]')
      expect(dbConnection.exists()).toBe(true)
    })

    it('sets DatabaseConnection to readonly mode', async () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: {
              template: '<div data-test="db-stub">DB Mock</div>',
              props: ['readonly'],
            },
          },
        },
      })

      if (wrapper.vm.activeTab !== undefined) {
        wrapper.vm.activeTab = 'database'
        await wrapper.vm.$nextTick()
      }

      const dbComponent = wrapper.findComponent({ name: 'DatabaseConnection' })
      if (dbComponent.exists()) {
        expect(dbComponent.props('readonly')).toBe(true)
      }
    })
  })

  describe('Network Settings Management', () => {
    it('loads network settings on mount', async () => {
      const mockConfig = {
        services: {
          external_host: 'localhost',
          api: { port: 7272 },
          frontend: { port: 7274 },
        },
        security: { cors: { allowed_origins: ['http://localhost:7274'] } },
      }

      global.fetch.mockImplementation((url) => {
        if (url.includes('/api/v1/config/database')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ database: { host: 'localhost', port: 5432 } }),
          })
        }
        if (url.includes('/api/v1/config')) {
          return Promise.resolve({
            ok: true,
            json: async () => mockConfig,
          })
        }
        if (url.includes('/api/settings/cookie-domains')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ domains: [] }),
          })
        }
        return Promise.reject(new Error('Unmocked fetch'))
      })

      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })

      await wrapper.vm.$nextTick()
      await new Promise((resolve) => setTimeout(resolve, 0))

      // Check that config endpoint was called
      const configCalls = global.fetch.mock.calls.filter(
        (call) => call[0].includes('/api/v1/config') && !call[0].includes('/database'),
      )
      expect(configCalls.length).toBeGreaterThan(0)
    })

    it('maintains loadNetworkSettings method for child component events', async () => {
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
            NetworkSettingsTab: { template: '<div>Network Tab</div>' },

            SystemPromptTab: { template: '<div>System Tab</div>' },
          },
        },
      })

      // The method should exist to handle events from NetworkSettingsTab
      expect(typeof wrapper.vm.loadNetworkSettings).toBe('function')
    })
  })

  describe('Admin Access', () => {
    it('should only be accessible to admin users', () => {
      // This will be enforced by router guard
      wrapper = mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
          },
        },
      })

      expect(wrapper.exists()).toBe(true)
      // Actual admin check happens in router guard
    })
  })

  // ── FE-9553: loadDatabaseSettings is silent unless a click asked ─────────
  //
  // It runs from onMounted AND from the retry button. Only the retry follows a
  // click, so only the retry may speak. Both directions asserted, because a
  // silence test alone would be satisfied by a guard that is always off.
  //
  // Note the retry button had to change too: `@click="loadDatabaseSettings"`
  // hands the MouseEvent in as the options object, which would have made
  // `notify` undefined and the retry silent. It now calls explicitly.
  describe('the notify opt-in (FE-9553)', () => {
    function mountIt() {
      return mount(SystemSettings, {
        global: {
          plugins: [vuetify, router, pinia],
          stubs: {
            DatabaseConnection: { template: '<div>Database Connection Mock</div>' },
            UserManager: { template: '<div>User Manager Mock</div>' },
          },
        },
      })
    }

    it('says NOTHING when the mount-time database read fails', async () => {
      global.fetch.mockRejectedValue(new Error('Network error'))
      showToastSpy.mockClear()

      wrapper = mountIt()
      await flushPromises()

      expect(showToastSpy).not.toHaveBeenCalled()
    })

    it('DOES speak up when the retry button asked for it', async () => {
      wrapper = mountIt()
      await flushPromises()

      global.fetch.mockRejectedValue(new Error('Network error'))
      showToastSpy.mockClear()
      await wrapper.vm.loadDatabaseSettings({ notify: true })
      await flushPromises()

      expect(showToastSpy).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    })
  })
})
