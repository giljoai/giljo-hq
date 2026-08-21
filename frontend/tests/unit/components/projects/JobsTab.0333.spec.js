/**
 * JobsTab.0333.spec.js
 *
 * Handover 0333: Execution Mode Toggle Migration (Phase 3)
 *
 * Tests for shouldShowCopyButton behavior based on execution mode from project prop.
 *
 * Following TDD: Write tests FIRST, implement to pass tests.
 *
 * Requirements:
 * 1. No execution mode toggle UI on JobsTab (removed)
 * 2. shouldShowCopyButton uses execution_mode from project prop (read-only)
 * 3. Multi-Terminal: All waiting agents show copy button
 * 4. CLI Mode: Only waiting orchestrator shows copy button
 * 5. CLI Mode: Specialist agents don't show copy button
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsTab from '@/components/projects/JobsTab.vue'
import { useUserStore } from '@/stores/user'
import { useProjectStateStore } from '@/stores/projectStateStore'

const vuetify = createVuetify()

// FE-9427: JobsTab reaches useRouter() through useJobActions (openAgentThread
// pushes the named 'Hub' route). Mounted without a router that returned
// `undefined`, so the deep-link path was inert.
const hubRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})

// Mock API
vi.mock('@/services/api', () => ({
  api: {
    prompts: {
      agentPrompt: vi.fn().mockResolvedValue({
        data: { prompt: 'Mock prompt text' },
      }),
    },
    post: vi.fn().mockResolvedValue({
      data: { success: true },
    }),
    messages: {
      sendUnified: vi.fn().mockResolvedValue({
        data: { success: true },
      }),
    },
  },
}))

// Mock toast
let mockShowToast
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    showToast: mockShowToast,
  }),
}))

const createMockJob = (overrides = {}) => ({
  job_id: 'job-' + Math.random().toString(36).slice(2, 9),
  agent_type: 'implementer',
  agent_name: 'Implementer Agent',
  status: 'waiting',
  mission_read_at: null,
  messages: [],
  ...overrides,
})

describe('JobsTab shouldShowCopyButton behavior (0333 Phase 3)', () => {
  let pinia

  const mockProject = (executionMode = 'multi_terminal') => ({
    project_id: 'proj-123',
    id: 'proj-123',
    name: 'Test Project',
    execution_mode: executionMode,
  })

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)

    const userStore = useUserStore()
    userStore.currentUser = {
      id: 'user-1',
      tenant_key: 'tenant-123',
    }

    // Seed projectStateStore with stagingComplete=true so shouldShowCopyButton
    // (moved to usePlayButton composable) progresses past the staging guard.
    const projectStateStore = useProjectStateStore()
    projectStateStore.setStagingComplete('proj-123', true)

    mockShowToast = vi.fn()
  })

  describe('Toggle Removal', () => {
    it('should NOT render execution mode toggle on JobsTab', async () => {
      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('multi_terminal'),
          agents: [],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      // No toggle should exist
      const toggleElements = wrapper.findAll('[class*="claude-toggle-bar"]')
      expect(toggleElements).toHaveLength(0)
    })
  })

  describe('Multi-Terminal Mode', () => {
    it('should return true for waiting implementer agent in Multi-Terminal mode', async () => {
      const job = createMockJob({
        agent_type: 'implementer',
        status: 'waiting',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('multi_terminal'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const result = wrapper.vm.shouldShowCopyButton(job)
      expect(result).toBe(true)
    })

    it('should return true for waiting tester agent in Multi-Terminal mode', async () => {
      const job = createMockJob({
        agent_type: 'tester',
        status: 'waiting',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('multi_terminal'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const result = wrapper.vm.shouldShowCopyButton(job)
      expect(result).toBe(true)
    })

    it('should return true for waiting orchestrator in Multi-Terminal mode', async () => {
      const job = createMockJob({
        agent_type: 'orchestrator',
        status: 'waiting',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('multi_terminal'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const result = wrapper.vm.shouldShowCopyButton(job)
      expect(result).toBe(true)
    })

    it('should return true for non-waiting agents in Multi-Terminal mode (prompt re-copying)', async () => {
      const job = createMockJob({
        agent_type: 'implementer',
        agent_display_name: 'implementer',
        status: 'working',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('multi_terminal'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const result = wrapper.vm.shouldShowCopyButton(job)
      expect(result).toBe(true)
    })
  })

  describe('Claude Code CLI Mode', () => {
    it('should return true for waiting orchestrator in CLI mode', async () => {
      const job = createMockJob({
        agent_type: 'orchestrator',
        agent_display_name: 'orchestrator',
        status: 'waiting',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('claude_code_cli'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const result = wrapper.vm.shouldShowCopyButton(job)
      expect(result).toBe(true)
    })

    it('should return false for waiting implementer in CLI mode', async () => {
      const job = createMockJob({
        agent_type: 'implementer',
        status: 'waiting',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('claude_code_cli'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const result = wrapper.vm.shouldShowCopyButton(job)
      expect(result).toBe(false)
    })

    it('should return false for waiting tester in CLI mode', async () => {
      const job = createMockJob({
        agent_type: 'tester',
        status: 'waiting',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('claude_code_cli'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const result = wrapper.vm.shouldShowCopyButton(job)
      expect(result).toBe(false)
    })

    it('should return false for waiting reviewer in CLI mode', async () => {
      const job = createMockJob({
        agent_type: 'reviewer',
        status: 'waiting',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('claude_code_cli'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const result = wrapper.vm.shouldShowCopyButton(job)
      expect(result).toBe(false)
    })
  })

  describe('Agent Table Still Visible', () => {
    it('should display agent jobs table in CLI mode', async () => {
      const job = createMockJob({
        agent_type: 'implementer',
        status: 'waiting',
      })

      const wrapper = mount(JobsTab, {
        props: {
          project: mockProject('claude_code_cli'),
          agents: [job],
          messages: [],
          allAgentsComplete: false,
        },
        global: {
          plugins: [pinia, vuetify, hubRouter],
          stubs: {
            'v-tooltip': true,
            'v-dialog': true,
            'v-card': true,
            'v-card-title': true,
            'v-card-text': true,
            'v-card-actions': true,
            'v-spacer': true,
            'v-text-field': true,
            'v-icon': true,
            'v-avatar': true,
            'v-btn': true,
            LaunchSuccessorDialog: true,
            AgentDetailsModal: true,
            CloseoutModal: true,
          },
        },
      })

      const table = wrapper.find('[data-testid="agent-status-table"]')
      expect(table.exists()).toBe(true)
    })
  })
})
