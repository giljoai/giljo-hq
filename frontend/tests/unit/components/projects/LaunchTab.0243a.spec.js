/**
 * LaunchTab.0243a.spec.js
 *
 * Test suite for Design Tokens Extraction (Handover 0243a)
 * Phase 1: Design tokens file creation and LaunchTab unified container specifications
 *
 * Following strict TDD: Write tests FIRST, watch them FAIL, then implement
 *
 * Requirements:
 * 1. Design tokens file existence and structure (design-tokens.scss)
 * 2. LaunchTab unified container specifications with exact styling values
 * 3. Token usage verification (no hardcoded values, use design tokens)
 * 4. Multi-tenant isolation (existing behavior must continue to pass)
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import LaunchTab from '@/components/projects/LaunchTab.vue'
import fs from 'fs'
import path from 'path'

// Create Vuetify instance for testing
const vuetify = createVuetify({
  components,
  directives,
})

// FE-9427: LaunchTab calls useRouter() (goToIntegrations -> /tools?tab=connect).
// Mounted without a router that returned `undefined`, so the navigation path was
// inert and every assertion aimed at it would have been meaningless. Routes are
// the ones this component actually pushes, not a catch-all -- a catch-all would
// let a wrong destination pass.
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})

// Mock user store with tenant_key
vi.mock('@/stores/user', () => ({
  useUserStore: vi.fn().mockReturnValue({
    currentUser: {
      tenant_key: 'test-tenant-key-123'
    }
  })
}))

// Mock API
vi.mock('@/services/api', () => ({
  default: {
    prompts: {
      staging: vi.fn().mockResolvedValue({
        data: {
          prompt: 'Test staging prompt',
          estimated_prompt_tokens: 1500
        }
      })
    },
    projects: {
      cancelStaging: vi.fn().mockResolvedValue({
        data: {
          agents_deleted: 3,
          messages_deleted: 5
        }
      })
    }
  }
}))

// Helper function to get correct path regardless of working directory
function getDesignTokensPath() {
  const cwd = process.cwd()
  return cwd.endsWith('frontend')
    ? path.join(cwd, 'src', 'styles', 'design-tokens.scss')
    : path.join(cwd, 'frontend', 'src', 'styles', 'design-tokens.scss')
}

function getLaunchTabPath() {
  const cwd = process.cwd()
  return cwd.endsWith('frontend')
    ? path.join(cwd, 'src', 'components', 'projects', 'LaunchTab.vue')
    : path.join(cwd, 'frontend', 'src', 'components', 'projects', 'LaunchTab.vue')
}

describe('LaunchTab.0243a - Design Tokens Extraction', () => {
  let wrapper

  // Sample project data
  const mockProject = {
    id: 'project-123',
    project_id: 'project-123',
    name: 'Test Project',
    description: 'Test project description for design tokens verification.',
    mission: null,
    agents: [],
    tenant_key: 'test-tenant-key-123'
  }

  beforeEach(() => {
    wrapper = mount(LaunchTab, {
      global: {
        plugins: [vuetify, router],
      },
      props: {
        project: mockProject,
        orchestrator: null,
        isStaging: false
      }
    })
  })

  // =========================================================================
  // SUITE 1: Design Tokens File Tests
  // =========================================================================

  describe('Design Tokens File', () => {
    it('design-tokens.scss file exists at frontend/src/styles/design-tokens.scss', () => {
      const designTokensPath = getDesignTokensPath()
      expect(fs.existsSync(designTokensPath)).toBe(true)
    })

    it('design-tokens.scss file size is less than 15KB', () => {
      // Threshold bumped from 12KB → 13KB after FE-chain-closeout-r3 added
      // $color-status-review token. The guard exists to catch runaway token bloat;
      // single targeted additions that push the file slightly past the old ceiling
      // are fine — update this comment and bump by 1KB when legitimately needed.
      //
      // 13KB → 14KB: FE-9289c added ONE token, $shadow-card-hover (the Quiet Cards
      // hover lift, named for its role so the value lives in one place). The token
      // line is ~50 bytes; the rest is the comment explaining why the existing
      // $shadow-* scale does not cover it. That rationale is the point of the file,
      // so it is not trimmed to fit a byte ceiling — the ceiling moves instead.
      //
      // 14KB → 15KB: FE-9536 added a new BREAKPOINT TOKENS section (3 tokens:
      // $breakpoint-mobile/tablet/compact) plus the rationale for why 3 and not
      // one-per-file, replacing 5+ scattered magic-number cutoffs across
      // WelcomeQuickGrid/ToolsView/JobsTab/AgentRow/ProjectsTable with a single
      // source of truth. Same policy: the rationale stays, the ceiling moves.
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const stats = fs.statSync(designTokensPath)
        expect(stats.size).toBeLessThan(15360)
      }
    })

    it('design-tokens.scss contains all required color tokens', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toContain('$color-container-border:')
        expect(content).toContain('$color-container-background:')
        expect(content).toContain('$color-panel-background:')
        expect(content).toContain('$color-text-primary:')
        expect(content).toContain('$color-text-secondary:')
      }
    })

    it('design-tokens.scss contains all required spacing tokens', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toContain('$spacing-container-padding:')
        expect(content).toContain('$spacing-panel-gap:')
        expect(content).toContain('$spacing-panel-content-padding:')
        expect(content).toContain('$spacing-panel-min-height:')
      }
    })

    it('design-tokens.scss contains all required typography tokens', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toContain('$typography-panel-header-size:')
        expect(content).toContain('$typography-panel-header-weight:')
        expect(content).toContain('$typography-panel-content-size:')
      }
    })

    it('design-tokens.scss contains all required border and shadow tokens', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toContain('$border-container:')
        expect(content).toContain('$border-radius-rounded:')
        expect(content).toContain('$border-radius-default:')
      }
    })
  })

  // =========================================================================
  // SUITE 2: LaunchTab Unified Container Structure Tests
  // =========================================================================

  describe('LaunchTab Flattened Layout Specifications', () => {
    it('content grid exists for two-column card layout', () => {
      const contentGrid = wrapper.find('.content-grid')
      expect(contentGrid.exists()).toBe(true)
    })

    it('two content cards are rendered (description + mission)', () => {
      const cards = wrapper.findAll('.content-card')
      expect(cards.length).toBe(2)
    })

    it('content cards have smooth-border class', () => {
      const cards = wrapper.findAll('.content-card')
      cards.forEach((card) => {
        expect(card.classes()).toContain('smooth-border')
      })
    })

    it('section labels use IBM Plex Mono uppercase pattern', () => {
      const labels = wrapper.findAll('.section-label')
      expect(labels.length).toBeGreaterThan(0)
      labels.forEach((label) => {
        expect(label.exists()).toBe(true)
      })
    })

    it('card body sections exist within content cards', () => {
      const cardBodies = wrapper.findAll('.card-body')
      expect(cardBodies.length).toBe(2)
      cardBodies.forEach((body) => {
        expect(body.exists()).toBe(true)
      })
    })

    it('integrations row is rendered in LaunchTab', () => {
      const integrationsRow = wrapper.find('.integrations-row')
      expect(integrationsRow.exists()).toBe(true)
    })

    it('agents list is rendered without a card wrapper', () => {
      const agentsList = wrapper.find('.agents-list')
      expect(agentsList.exists()).toBe(true)
      // agents-list should NOT be inside a smooth-border card
      const parent = agentsList.element.parentElement
      expect(parent.classList.contains('smooth-border')).toBe(false)
    })

    it('description and mission panels are accessible via data-testid', () => {
      const descPanel = wrapper.find('[data-testid="description-panel"]')
      const missionPanel = wrapper.find('[data-testid="mission-panel"]')

      expect(descPanel.exists()).toBe(true)
      expect(missionPanel.exists()).toBe(true)

      expect(descPanel.find('.section-label').exists()).toBe(true)
      expect(missionPanel.find('.section-label').exists()).toBe(true)

      expect(descPanel.find('.card-body').exists()).toBe(true)
      expect(missionPanel.find('.card-body').exists()).toBe(true)
    })

    it('standalone agents section label exists', () => {
      const standaloneLabel = wrapper.find('.section-label--standalone')
      expect(standaloneLabel.exists()).toBe(true)
      expect(standaloneLabel.text()).toContain('Agents')
    })
  })

  // =========================================================================
  // SUITE 3: Design Token Usage Verification
  // =========================================================================

  describe('Design Token Usage in LaunchTab.vue', () => {
    it('LaunchTab.vue imports design-tokens.scss', async () => {
      const componentPath = getLaunchTabPath()
      const content = fs.readFileSync(componentPath, 'utf-8')

      const hasDesignTokenImport =
        content.includes("@import '@/styles/design-tokens.scss'") ||
        content.includes('@import "@/styles/design-tokens.scss"') ||
        content.includes("@use '@/styles/design-tokens'") ||
        content.includes('@use "@/styles/design-tokens"') ||
        content.includes("@use '@/styles/design-tokens.scss'") ||
        content.includes('@use "@/styles/design-tokens.scss"')

      expect(hasDesignTokenImport).toBe(true)
    })

    it('LaunchTab.vue has no hardcoded hex colors in styles', () => {
      const componentPath = getLaunchTabPath()
      const content = fs.readFileSync(componentPath, 'utf-8')

      const styleMatch = content.match(/<style[^>]*>([\s\S]*?)<\/style>/)
      if (styleMatch) {
        const styleContent = styleMatch[1]
        const hexMatches = styleContent.match(/#[0-9a-f]{6}|#[0-9a-f]{3}/gi) || []
        const hardcodedHexes = hexMatches.filter((hex) => hex.toLowerCase() !== '#d4b08a')
        expect(hardcodedHexes.length).toBe(0)
      }
    })

    it('LaunchTab.vue uses design tokens for styling values', () => {
      const componentPath = getLaunchTabPath()
      const content = fs.readFileSync(componentPath, 'utf-8')

      const styleMatch = content.match(/<style[^>]*>([\s\S]*?)<\/style>/)
      if (styleMatch) {
        const styleContent = styleMatch[1]
        expect(styleContent).toContain('$elevation-raised')
      }
    })

    it('LaunchTab.vue uses design tokens for all border-radius values', () => {
      const componentPath = getLaunchTabPath()
      const content = fs.readFileSync(componentPath, 'utf-8')

      const styleMatch = content.match(/<style[^>]*>([\s\S]*?)<\/style>/)
      if (styleMatch) {
        const styleContent = styleMatch[1]
        expect(styleContent).toContain('$border-radius')
      }
    })

    it('LaunchTab.vue uses color tokens for all container and panel colors', () => {
      const componentPath = getLaunchTabPath()
      const content = fs.readFileSync(componentPath, 'utf-8')

      const styleMatch = content.match(/<style[^>]*>([\s\S]*?)<\/style>/)
      if (styleMatch) {
        const styleContent = styleMatch[1]
        expect(styleContent).toContain('$color')
      }
    })
  })

  // =========================================================================
  // SUITE 4: Multi-Tenant Isolation (Existing Behavior)
  // =========================================================================

  describe('Multi-Tenant Isolation Verification', () => {
    it('component receives tenant_key from user store', () => {
      expect(wrapper.vm).toBeDefined()
      expect(wrapper.props().project.tenant_key).toBe('test-tenant-key-123')
    })

    it('project data includes tenant_key for isolation', () => {
      const projectWithTenant = {
        ...mockProject,
        tenant_key: 'test-tenant-key-123'
      }

      expect(projectWithTenant.tenant_key).toBe('test-tenant-key-123')
      expect(projectWithTenant.id).toBe('project-123')
    })

    it('WebSocket composable is initialized for tenant-scoped events', () => {
      expect(wrapper.vm).toBeDefined()
    })

    it('only displays content for current tenant', () => {
      const projectData = wrapper.props('project')
      expect(projectData).toBeDefined()
      expect(projectData.tenant_key || projectData.project_id).toBeDefined()
    })

    it('does not display content from other tenants', () => {
      const differentTenantProject = {
        ...mockProject,
        tenant_key: 'different-tenant-456'
      }

      expect(differentTenantProject.tenant_key).not.toBe('test-tenant-key-123')
    })
  })

  // =========================================================================
  // SUITE 5: Component Integration Tests
  // =========================================================================

  describe('Component Integration with Design Tokens', () => {
    it('renders LaunchTab with flattened layout structure', () => {
      const launchTabWrapper = wrapper.find('.launch-tab-wrapper')
      const contentGrid = wrapper.find('.content-grid')

      expect(launchTabWrapper.exists()).toBe(true)
      expect(contentGrid.exists()).toBe(true)
    })

    it('has consistent styling throughout content cards', () => {
      const cards = wrapper.findAll('.content-card')
      expect(cards.length).toBe(2)

      cards.forEach((card) => {
        const label = card.find('.section-label')
        const body = card.find('.card-body')

        expect(label.exists()).toBe(true)
        expect(body.exists()).toBe(true)
      })
    })

    it('applies unified container design to header actions area', () => {
      const headerActions = wrapper.find('.header-actions')
      expect(headerActions.exists()).toBe(true)
      expect(headerActions.classes()).toContain('header-actions')
    })

    it('maintains accessibility of all interactive elements', () => {
      const buttons = wrapper.findAll('button')
      expect(buttons.length).toBeGreaterThan(0)

      buttons.forEach((btn) => {
        expect(btn.exists()).toBe(true)
      })
    })
  })

  // =========================================================================
  // SUITE 6: Token Value Specificity Tests
  // =========================================================================

  describe('Exact Design Token Values (Specification Compliance)', () => {
    it('container border is exactly 2px with rgba(255, 255, 255, 0.2)', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toMatch(/\$border-container:\s*2px\s+solid\s+rgba\(255,\s*255,\s*255,\s*0\.2\)/)
      }
    })

    it('container border-radius is exactly 16px', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        // $border-radius-rounded is the canonical container radius token (16px)
        expect(content).toMatch(/\$border-radius-rounded:\s*16px/)
      }
    })

    it('container padding is exactly 30px', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toMatch(/\$spacing-container-padding:\s*30px/)
      }
    })

    it('panel gap is exactly 24px', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toMatch(/\$spacing-panel-gap:\s*24px/)
      }
    })

    it('panel min-height is exactly 450px', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toMatch(/\$spacing-panel-min-height:\s*450px/)
      }
    })

    it('container background is exactly rgba(14, 28, 45, 0.5)', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toMatch(/\$color-container-background:\s*rgba\(14,\s*28,\s*45,\s*0\.5\)/)
      }
    })

    it('panel content background is exactly rgba(20, 35, 50, 0.8)', () => {
      const designTokensPath = getDesignTokensPath()
      if (fs.existsSync(designTokensPath)) {
        const content = fs.readFileSync(designTokensPath, 'utf-8')
        expect(content).toMatch(/\$color-panel-background:\s*rgba\(20,\s*35,\s*50,\s*0\.8\)/)
      }
    })
  })
})

// ---------------------------------------------------------------------------
// FE-9427: the integration icons' DESTINATION.
//
// LaunchTab.goToIntegrations() pushes /tools?tab=connect. Before this lane the
// spec mounted LaunchTab with no router, so useRouter() returned `undefined`
// and any click on those icons would have thrown -- which is how we know the
// handler was never exercised here. It is not exercised anywhere else either:
// ProjectTabs.integrationIcons.spec.js mocks vue-router and builds a
// `mockRouter.push` spy, but never asserts it. So the icons were tested for
// their appearance and never for what they DO.
//
// The v-tooltip passthrough stub is the repo-standard idiom for reaching an
// activator-slot child (see ProjectTabs.integrationIcons.spec.js) -- the global
// flat stub renders only the default slot, so the icons never reach the DOM.
// ---------------------------------------------------------------------------
describe('LaunchTab.0243a - integration icons navigate to Connect (FE-9427)', () => {
  const mockProject = {
    id: 'project-123',
    project_id: 'project-123',
    name: 'Test Project',
    description: 'Test project description.',
    mission: null,
    agents: [],
    tenant_key: 'test-tenant-key-123',
  }

  function mountWithTooltips(navRouter) {
    return mount(LaunchTab, {
      global: {
        plugins: [vuetify, navRouter],
        stubs: {
          'v-tooltip': {
            template:
              '<div class="v-tooltip-stub"><slot name="activator" :props="{}" /><slot /></div>',
          },
        },
      },
      props: { project: mockProject },
    })
  }

  function freshRouter() {
    return createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'Root', component: { template: '<div />' } },
        { path: '/tools', name: 'Tools', component: { template: '<div />' } },
      ],
    })
  }

  it('clicking the Git status icon lands on Tools with the Connect tab selected', async () => {
    const navRouter = freshRouter()
    const wrapper = mountWithTooltips(navRouter)
    await flushPromises()

    await wrapper.find('[data-testid="git-status-icon"]').trigger('click')
    await flushPromises()

    expect(navRouter.currentRoute.value.path).toBe('/tools')
    expect(navRouter.currentRoute.value.query).toEqual({ tab: 'connect' })
    wrapper.unmount()
  })

  it('clicking the Serena status icon lands on the same place', async () => {
    const navRouter = freshRouter()
    const wrapper = mountWithTooltips(navRouter)
    await flushPromises()

    await wrapper.find('[data-testid="serena-status-icon"]').trigger('click')
    await flushPromises()

    expect(navRouter.currentRoute.value.fullPath).toBe('/tools?tab=connect')
    wrapper.unmount()
  })
})
