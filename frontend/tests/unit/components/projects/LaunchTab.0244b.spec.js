/**
 * LaunchTab.0244b.spec.js
 *
 * Test suite for Agent Mission Edit Functionality (Handover 0244b)
 * Integration tests for AgentMissionEditModal in LaunchTab
 *
 * Post-refactor notes:
 * - LaunchTab uses useAgentJobs() composable for agent data (sortedJobs), NOT project.agents prop
 * - handleAgentEdit checks agent.agent_display_name (not agent_type)
 * - handleMissionUpdated calls agentJobsStore.upsertJob, not local array mutation
 * - No WebSocket on/off for agent:mission_updated in LaunchTab (removed)
 * - Toast calls use { message, type } without timeout
 * - LaunchTab has gitEnabled and serenaEnabled props
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { nextTick } from 'vue'
import LaunchTab from '@/components/projects/LaunchTab.vue'

// Create Vuetify instance for testing
const vuetify = createVuetify({
  components,
  directives,
})

// FE-9427: LaunchTab calls useRouter() (goToIntegrations -> /tools?tab=connect).
// Without a router installed that returned `undefined`, so the navigation path
// was inert. Routes are the ones this component actually pushes.
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})

// Mock useAgentJobs composable
const mockSortedJobs = { value: [] }

vi.mock('@/composables/useAgentJobs', () => ({
  useAgentJobs: () => ({
    sortedJobs: mockSortedJobs,
  })
}))

// Mock agentJobsStore
const mockUpsertJob = vi.fn()

vi.mock('@/stores/agentJobsStore', () => ({
  useAgentJobsStore: () => ({
    upsertJob: mockUpsertJob,
  })
}))

// Mock projectStateStore
vi.mock('@/stores/projectStateStore', () => ({
  useProjectStateStore: () => ({
    getProjectState: vi.fn().mockReturnValue({ mission: '' }),
  })
}))

// Mock Toast composable
let mockShowToast

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    showToast: mockShowToast,
  })
}))

// Mock user store with tenant_key
vi.mock('@/stores/user', () => ({
  useUserStore: vi.fn().mockReturnValue({
    currentUser: {
      tenant_key: 'test-tenant-key-123'
    }
  })
}))

// Mock agentColors -- only getAgentColor's return shape is faked;
// getAgentColorKey/getAgentInitials (FE-9490) keep their REAL implementation
// via importOriginal, since LaunchTab now delegates to them directly.
vi.mock('@/config/agentColors', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    getAgentColor: () => ({ hex: '#888888', name: 'grey' }),
  }
})

describe('LaunchTab - Agent Mission Edit Integration (0244b)', () => {
  let wrapper

  const mockProject = {
    id: 'project-123',
    project_id: 'project-123',
    name: 'Test Project',
    mission: 'Test project mission',
    description: 'Test project description',
  }

  const mockOrchestrator = {
    id: 'orch-123',
    agent_display_name: 'orchestrator',
    agent_name: 'Orchestrator',
    mission: 'Orchestrate the project',
    status: 'active',
  }

  const mockAgent = {
    id: 'agent-456',
    agent_display_name: 'implementer',
    agent_name: 'Implementor Agent',
    mission: 'Original implementation mission',
    status: 'pending',
  }

  beforeEach(() => {
    mockShowToast = vi.fn()
    mockUpsertJob.mockReset()
    mockSortedJobs.value = []
  })

  describe('Component Integration', () => {
    it('should import and register AgentMissionEditModal component', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
        },
      })

      // Check that the component imports exist
      expect(wrapper.vm).toBeDefined()
      expect(wrapper.findComponent({ name: 'AgentMissionEditModal' })).toBeDefined()
    })

    it('should have showMissionEditModal and selectedAgentForEdit state', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
        },
      })

      // Access component instance to check reactive state
      expect(wrapper.vm.showMissionEditModal).toBeDefined()
      expect(wrapper.vm.selectedAgentForEdit).toBeDefined()
      expect(wrapper.vm.showMissionEditModal).toBe(false)
      expect(wrapper.vm.selectedAgentForEdit).toBeNull()
    })
  })

  describe('handleAgentEdit Function', () => {
    it('should open modal for non-orchestrator agents', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
        },
      })

      // Call handleAgentEdit with non-orchestrator agent
      wrapper.vm.handleAgentEdit(mockAgent)
      await nextTick()

      // Modal should be visible
      expect(wrapper.vm.showMissionEditModal).toBe(true)
      expect(wrapper.vm.selectedAgentForEdit).toEqual(mockAgent)
    })

    it('should show info toast for orchestrator and not open modal', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
        },
      })

      // Call handleAgentEdit with orchestrator
      wrapper.vm.handleAgentEdit(mockOrchestrator)
      await nextTick()

      // Modal should NOT be visible
      expect(wrapper.vm.showMissionEditModal).toBe(false)

      // Toast notification should be shown
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Orchestrator configuration cannot be edited here',
          type: 'info',
        })
      )
    })
  })

  describe('handleMissionUpdated Function', () => {
    it('should call agentJobsStore.upsertJob when mission is updated', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
        },
      })

      await nextTick()

      // Call handleMissionUpdated with new mission
      const updatedMission = 'Updated mission text'
      wrapper.vm.handleMissionUpdated({
        jobId: 'agent-456',
        mission: updatedMission,
      })
      await nextTick()

      // Verify agentJobsStore.upsertJob was called
      expect(mockUpsertJob).toHaveBeenCalledWith({ job_id: 'agent-456', mission: updatedMission })

      // Verify success toast was shown
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Agent mission updated successfully',
          type: 'success',
        })
      )
    })

    it('should handle mission update for non-existent agent gracefully', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
        },
      })

      // Call with non-existent job ID - should not crash
      wrapper.vm.handleMissionUpdated({
        jobId: 'non-existent-id',
        mission: 'Some mission',
      })
      await nextTick()

      // Should still show toast
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Agent mission updated successfully',
          type: 'success',
        })
      )
    })
  })

  describe('Template Integration', () => {
    it('should render AgentMissionEditModal in template', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
          stubs: {
            AgentMissionEditModal: {
              template: '<div class="agent-mission-edit-modal-stub"></div>',
              props: ['modelValue', 'agent'],
            },
          },
        },
      })

      // Check that modal stub is rendered
      expect(wrapper.find('.agent-mission-edit-modal-stub').exists()).toBe(true)
    })

    it('should pass correct props to AgentMissionEditModal', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
        },
      })

      // Open modal
      wrapper.vm.handleAgentEdit(mockAgent)
      await nextTick()

      // Find modal component
      const modal = wrapper.findComponent({ name: 'AgentMissionEditModal' })

      // Check props
      expect(modal.props('modelValue')).toBe(true)
      expect(modal.props('agent')).toEqual(mockAgent)
    })

    it('should handle mission-updated event from modal', async () => {
      wrapper = mount(LaunchTab, {
        props: {
          project: mockProject,
          orchestrator: mockOrchestrator,
          isStaging: false,
        },
        global: {
          plugins: [vuetify, router],
        },
      })

      await nextTick()

      // Open modal
      wrapper.vm.handleAgentEdit(mockAgent)
      await nextTick()

      // Find modal and emit event
      const modal = wrapper.findComponent({ name: 'AgentMissionEditModal' })
      modal.vm.$emit('mission-updated', {
        jobId: 'agent-456',
        mission: 'Updated via modal',
      })
      await nextTick()

      // Verify upsertJob was called
      expect(mockUpsertJob).toHaveBeenCalledWith({ job_id: 'agent-456', mission: 'Updated via modal' })
    })
  })
})
