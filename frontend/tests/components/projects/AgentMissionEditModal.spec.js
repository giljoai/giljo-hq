import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { nextTick } from 'vue'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentMissionEditModal from '@/components/projects/AgentMissionEditModal.vue'
import api from '@/services/api'

describe('AgentMissionEditModal.vue', () => {
  let wrapper
  let pinia
  let vuetify
  let mockApiClient

  const mockAgent = {
    id: 'job-123',
    agent_name: 'Test Implementor',
    agent_type: 'implementor',
    mission: 'Original mission text for testing',
    background_color: 'primary',
  }

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify({
      components,
      directives,
    })

    // Mock API client
    mockApiClient = {
      agentJobs: {
        updateMission: vi.fn().mockResolvedValue({
          data: { success: true, job_id: 'job-123', mission: 'Updated mission' },
        }),
      },
    }

    // Mock window.confirm
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
    vi.restoreAllMocks()
  })

  const createWrapper = (props = {}, global = {}) => {
    const defaultGlobal = {
      plugins: [pinia, vuetify],
      mocks: {
        $api: mockApiClient,
      },
    }

    // Merge global objects properly
    const mergedGlobal = {
      ...defaultGlobal,
      ...global,
      mocks: {
        ...defaultGlobal.mocks,
        ...(global.mocks || {}),
      },
    }

    return mount(AgentMissionEditModal, {
      props: {
        modelValue: false,
        agent: mockAgent,
        ...props,
      },
      global: mergedGlobal,
      attachTo: document.body,
    })
  }

  describe('Component Initialization', () => {
    it('renders component', () => {
      wrapper = createWrapper({ modelValue: true })
      expect(wrapper.exists()).toBe(true)
    })

    it('loads agent mission on mount', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      // Check internal state via vm
      expect(wrapper.vm.missionText).toBe('Original mission text for testing')
      expect(wrapper.vm.originalMission).toBe('Original mission text for testing')
    })

    it('initializes with no changes', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      expect(wrapper.vm.hasChanges).toBe(false)
    })
  })

  describe('Mission State Management', () => {
    it('tracks character count correctly', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      expect(wrapper.vm.characterCount).toBe(33)

      wrapper.vm.missionText = 'Short'
      await nextTick()

      expect(wrapper.vm.characterCount).toBe(5)
    })

    it('detects changes when mission is modified', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      expect(wrapper.vm.hasChanges).toBe(false)

      wrapper.vm.missionText = 'Updated mission text'
      await nextTick()

      expect(wrapper.vm.hasChanges).toBe(true)
    })

    it('resets mission to original', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'Changed mission'
      await nextTick()
      expect(wrapper.vm.hasChanges).toBe(true)

      wrapper.vm.resetToOriginal()
      await nextTick()

      expect(wrapper.vm.missionText).toBe('Original mission text for testing')
      expect(wrapper.vm.hasChanges).toBe(false)
    })
  })

  describe('Validation Logic', () => {
    it('validates empty mission as invalid', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = ''
      await nextTick()

      expect(wrapper.vm.isValid).toBe(false)
    })

    it('validates whitespace-only mission as invalid', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = '   '
      await nextTick()

      expect(wrapper.vm.isValid).toBe(false)
    })

    it('validates mission exceeding 50,000 characters as invalid', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'x'.repeat(50001)
      await nextTick()

      expect(wrapper.vm.isValid).toBe(false)
    })

    it('validates mission at 50,000 characters as valid', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'x'.repeat(50000)
      await nextTick()

      expect(wrapper.vm.isValid).toBe(true)
    })

    it('validates normal mission as valid', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'Valid mission text'
      await nextTick()

      expect(wrapper.vm.isValid).toBe(true)
    })
  })

  describe('API Integration', () => {
    it('calls API with correct parameters on save', async () => {
      api.agentJobs.updateMission.mockResolvedValue({
        data: { success: true, job_id: 'job-123', mission: 'New mission from test' },
      })

      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'New mission from test'
      await nextTick()

      await wrapper.vm.saveMission()
      await flushPromises()

      expect(api.agentJobs.updateMission).toHaveBeenCalledWith('job-123', {
        mission: 'New mission from test',
      })
    })

    it('emits mission-updated event after successful save', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'New mission'
      await nextTick()

      await wrapper.vm.saveMission()
      await flushPromises()
      await nextTick()

      const emitted = wrapper.emitted('mission-updated')
      expect(emitted).toBeTruthy()
      expect(emitted[0][0]).toEqual({
        jobId: 'job-123',
        mission: 'New mission',
      })
    })

    it('closes modal after successful save', async () => {
      api.agentJobs.updateMission.mockResolvedValue({
        data: { success: true, job_id: 'job-123', mission: 'New mission' },
      })

      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'New mission'
      await nextTick()

      await wrapper.vm.saveMission()
      await flushPromises()
      await nextTick()

      // After successful save, the component emits update:modelValue with false to close the modal
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted[emitted.length - 1][0]).toBe(false)
    })

    it('shows loading state during API call', async () => {
      // Use a slow mock that we can control
      let resolvePromise
      api.agentJobs.updateMission.mockImplementation(() => new Promise((resolve) => {
        resolvePromise = resolve
      }))

      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'New mission'
      await nextTick()

      // Start save - don't await yet
      const savePromise = wrapper.vm.saveMission()

      // Check loading state immediately (should be synchronous)
      expect(wrapper.vm.loading).toBe(true)

      // Resolve the API call
      resolvePromise({ data: { success: true } })
      await savePromise
      await flushPromises()

      expect(wrapper.vm.loading).toBe(false)
    })

    it('displays error message on API failure', async () => {
      api.agentJobs.updateMission.mockRejectedValue({
        response: { data: { error_code: 'VALIDATIONERROR', message: 'Custom error message' } },
      })

      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'New mission'
      await nextTick()

      await wrapper.vm.saveMission()
      await flushPromises()

      expect(wrapper.vm.error).toBe('Custom error message')
    })

    it('keeps modal open on API failure', async () => {
      const failingApiClient = {
        agentJobs: {
          updateMission: vi.fn().mockRejectedValue(new Error('Network error')),
        },
      }

      wrapper = createWrapper(
        { modelValue: true },
        {
          mocks: {
            $api: failingApiClient,
          },
        },
      )
      await nextTick()

      wrapper.vm.missionText = 'New mission'
      await nextTick()

      await wrapper.vm.saveMission()
      await flushPromises()

      // Modal should still be open (isOpen should still be true)
      expect(wrapper.vm.isOpen).toBe(true)
    })

    it('does not call API when mission is invalid', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = '' // Invalid
      await nextTick()

      await wrapper.vm.saveMission()
      await flushPromises()

      expect(mockApiClient.agentJobs.updateMission).not.toHaveBeenCalled()
    })

    it('does not call API when no changes exist', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      // Mission text unchanged
      await wrapper.vm.saveMission()
      await flushPromises()

      expect(mockApiClient.agentJobs.updateMission).not.toHaveBeenCalled()
    })
  })

  describe('Modal Closing Behavior', () => {
    it('closes without confirmation when no changes', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.handleClose()
      await nextTick()

      expect(window.confirm).not.toHaveBeenCalled()

      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted[emitted.length - 1][0]).toBe(false)
    })

    it('shows confirmation dialog when closing with unsaved changes', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'Changed text'
      await nextTick()

      wrapper.vm.handleClose()
      await nextTick()

      // Component now uses a v-dialog (showDiscardDialog) instead of window.confirm
      expect(wrapper.vm.showDiscardDialog).toBe(true)
    })

    it('keeps modal open when user does not confirm discard', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'Changed text'
      await nextTick()

      wrapper.vm.handleClose()
      await nextTick()

      // Discard dialog is shown but user dismisses it (sets showDiscardDialog to false)
      wrapper.vm.showDiscardDialog = false
      await nextTick()

      // Modal should still be open - no update:modelValue emitted with false
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeFalsy()
    })

    it('closes modal and resets when user confirms discard', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'Changed text'
      await nextTick()

      wrapper.vm.handleClose()
      await nextTick()

      // User confirms via discardAndClose method
      wrapper.vm.discardAndClose()
      await nextTick()

      // Mission should be reset
      expect(wrapper.vm.missionText).toBe('Original mission text for testing')

      // Modal should close
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted[emitted.length - 1][0]).toBe(false)
    })
  })

  describe('Agent Prop Updates', () => {
    it('updates mission text when agent prop changes', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      expect(wrapper.vm.missionText).toBe('Original mission text for testing')

      // Update agent prop
      await wrapper.setProps({
        agent: {
          ...mockAgent,
          mission: 'New mission from prop update',
        },
      })
      await nextTick()

      expect(wrapper.vm.missionText).toBe('New mission from prop update')
      expect(wrapper.vm.originalMission).toBe('New mission from prop update')
    })

    it('handles agent without mission field', async () => {
      const agentWithoutMission = {
        id: 'job-456',
        agent_name: 'Test Agent',
        agent_type: 'tester',
      }

      wrapper = createWrapper({ modelValue: true, agent: agentWithoutMission })
      await nextTick()

      expect(wrapper.vm.missionText).toBe('')
      expect(wrapper.vm.originalMission).toBe('')
    })

    it('handles null agent gracefully', async () => {
      wrapper = createWrapper({ modelValue: true, agent: null })
      await nextTick()

      expect(wrapper.vm.missionText).toBe('')
      expect(wrapper.vm.originalMission).toBe('')
    })

    it('clears error when agent changes', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.error = 'Some error'
      await nextTick()

      // Update agent prop
      await wrapper.setProps({
        agent: {
          ...mockAgent,
          mission: 'Different mission',
        },
      })
      await nextTick()

      expect(wrapper.vm.error).toBeNull()
    })
  })

  describe('Computed Properties', () => {
    it('computes isOpen from modelValue prop', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      expect(wrapper.vm.isOpen).toBe(true)

      await wrapper.setProps({ modelValue: false })
      await nextTick()

      expect(wrapper.vm.isOpen).toBe(false)
    })
  })

  describe('Error Handling', () => {
    it('clears error when set to null', async () => {
      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.error = 'Test error'
      await nextTick()
      expect(wrapper.vm.error).toBe('Test error')

      wrapper.vm.error = null
      await nextTick()
      expect(wrapper.vm.error).toBeNull()
    })

    it('handles generic API errors', async () => {
      api.agentJobs.updateMission.mockRejectedValue(new Error('Network failure'))

      wrapper = createWrapper({ modelValue: true })
      await nextTick()

      wrapper.vm.missionText = 'New mission'
      await nextTick()

      await wrapper.vm.saveMission()
      await flushPromises()

      expect(wrapper.vm.error).toBe('Network failure')
    })
  })
})
