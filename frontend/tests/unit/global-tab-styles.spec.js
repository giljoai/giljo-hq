/**
 * Test: Global Tab Styling Standardization
 *
 * Tests for consistent tab styling across the application.
 *
 * Post-refactor notes:
 * - ProductForm uses v-btn-toggle for tab navigation
 * - ProjectTabs uses pill-button toggles (0871c)
 * - SystemSettings uses pill-button toggles (0871b)
 * - global-tabs-window class is used on v-window for tab content
 *
 * Components tested:
 * - ProjectTabs.vue (pill-toggle buttons)
 * - SystemSettings.vue (pill-toggle buttons)
 * - ProductForm.vue (v-btn-toggle)
 *
 * Note on testing strategy:
 * The global test setup (tests/setup.js) mocks Vuetify components with
 * simple HTML stubs, so v-window renders as a <div class="v-window"> stub
 * that does not preserve parent-template classes. For the global-tabs-window
 * class test we read the source file statically instead.
 *
 * FE-9397 corrected this header. It previously instructed the next author to
 * rely on v-btn-toggle being ABSENT from the global stubs and rendering as an
 * unresolved custom element. That was the defect, written down as strategy: an
 * unresolved component still renders its tag, its class and its default slot,
 * so `expect(html).toContain('v-btn-toggle')` was true whether the toggle
 * worked, was inert, or was stubbed — an assertion that could not fail. The
 * component is registered now and unresolved components fail the run, so
 * assert on structure that can actually break.
 *
 * Caution while reading below: the `createVuetify({ components, directives })`
 * this file builds registers NOTHING. tests/setup.js mocks the `vuetify`
 * module, so that import returns a no-op `install`. It is retained only
 * because the mounts pass it as a plugin; do not read it as evidence that
 * these tests run against real Vuetify.
 */

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// Import components to test
import SystemSettings from '@/views/SystemSettings.vue'
import ProductForm from '@/components/products/ProductForm.vue'

// Mock dependencies
vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: {},
    hash: '',
  }),
  useRouter: () => ({
    replace: vi.fn(),
    currentRoute: { value: { query: {} } },
  }),
}))

vi.mock('@/services/api', () => ({
  default: {
    products: {
      getGitIntegration: vi.fn().mockResolvedValue({ data: { enabled: false } }),
      updateGitIntegration: vi.fn().mockResolvedValue({ data: { enabled: false } }),
    },
    users: {
      getFieldToggleConfig: vi.fn().mockResolvedValue({ data: { priorities: {} } }),
    },
  },
}))

vi.mock('@/services/setupService', () => ({
  default: {
  },
}))

const vuetify = createVuetify({ components, directives })

// Create shared global stubs for all tests
const globalStubs = {
  LaunchTab: true,
  JobsTab: true,
  TemplateManager: true,
  ApiKeyManager: true,
  AgentExport: true,
  ContextPriorityConfig: true,
  McpIntegrationCard: true,
  GitIntegrationCard: true,

  ProductIntroTour: true,
  NetworkSettingsTab: true,
  DatabaseConnection: true,
  // SecuritySettingsTab retired in FE-6245 (Cookie Whitelist moved to NetworkSettingsTab)
  SystemPromptTab: true,
  CloseoutModal: true,
}

describe('Global Tab Styles', () => {
  // FE-9681: the ProjectTabs pill-toggle case retired with the project page;
  // the Jobs board's side and filter segments carry the pill pattern now.
  describe('SystemSettings Component', () => {
    it('uses pill-toggle buttons for tab navigation', async () => {
      const pinia = createPinia()
      const wrapper = mount(SystemSettings, {
        global: {
          plugins: [pinia, vuetify],
          stubs: globalStubs,
        },
      })

      await wrapper.vm.$nextTick()

      const pills = wrapper.findAll('.pill-toggle')
      // FE-6245: Security tab retired (Cookie Whitelist moved to Network tab); CE now has 3 pills.
      // IMP-5042: Prompts tab already moved to Account -> Danger Zone.
      expect(pills.length).toBe(3)
      expect(wrapper.find('.pill-toggle-row').exists()).toBe(true)
    })

    it('uses global-tabs-window class on v-window', () => {
      // Static source code verification
      const srcPath = resolve(__dirname, '../../src/views/SystemSettings.vue')
      const source = readFileSync(srcPath, 'utf-8')
      expect(source).toContain('global-tabs-window')
      expect(source).toContain('<v-window')
    })
  })

  describe('ProductForm Component', () => {
    it('uses v-btn-toggle for tab navigation', async () => {
      const pinia = createPinia()
      const wrapper = mount(ProductForm, {
        props: {
          modelValue: true,
          product: null,
          isEdit: false,
        },
        global: {
          plugins: [pinia, vuetify],
          stubs: globalStubs,
        },
      })

      await wrapper.vm.$nextTick()

      // FE-9397: assert the tabs live INSIDE the toggle. The old
      // `expect(html).toContain('v-btn-toggle')` held even when the toggle was
      // an inert unresolved element, so it proved nothing.
      const toggle = wrapper.find('.v-btn-toggle')
      expect(toggle.exists()).toBe(true)
      expect(toggle.find('[data-testid="product-form-tab-setup"]').exists()).toBe(true)
      expect(toggle.find('[data-testid="product-form-tab-info"]').exists()).toBe(true)
    })

    it('does not use global-tabs-window on ProductForm (dialog-based)', () => {
      // ProductForm uses a bordered-tabs-content pattern inside a dialog,
      // not the global-tabs-window class used by full-page views.
      const srcPath = resolve(__dirname, '../../src/components/products/ProductForm.vue')
      const source = readFileSync(srcPath, 'utf-8')
      expect(source).toContain('bordered-tabs-content')
    })
  })

  describe('Tab Class Consistency', () => {
    it('ProductForm uses v-btn-toggle', async () => {
      const pinia = createPinia()

      const wrapper = mount(ProductForm, {
        props: { modelValue: true, product: null, isEdit: false },
        global: {
          plugins: [pinia, vuetify],
          stubs: globalStubs,
        },
      })

      await wrapper.vm.$nextTick()

      // FE-9397: see the sibling assertion above — a raw string match on the
      // rendered HTML could not distinguish a working toggle from a missing one.
      const toggle = wrapper.find('.v-btn-toggle')
      expect(toggle.exists()).toBe(true)
      expect(toggle.findAll('[data-testid^="product-form-tab-"]').length).toBeGreaterThanOrEqual(2)
    })

    // FE-9681: the ProjectTabs case retired with the project page.

    it('SystemSettings uses pill-toggle buttons', async () => {
      const pinia = createPinia()

      const configs = [
        // FE-6245: Security tab retired; CE now has 3 pills (Identity, Network, Database).
        // IMP-5042: Prompts tab already moved to Account -> Danger Zone.
        { name: 'SystemSettings', component: SystemSettings, props: {}, expectedPills: 3 },
      ]

      for (const config of configs) {
        const wrapper = mount(config.component, {
          props: config.props,
          global: {
            plugins: [pinia, vuetify],
            stubs: globalStubs,
          },
        })

        await wrapper.vm.$nextTick()

        const pills = wrapper.findAll('.pill-toggle')
        expect(pills.length).toBe(config.expectedPills)
      }
    })
  })
})
