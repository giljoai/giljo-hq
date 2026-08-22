/**
 * Test suite for AgentDetailsModal component
 *
 * Tests the modal that displays agent template preview or orchestrator prompt
 * when clicking the info button on agent cards in LaunchTab/JobsTab.
 *
 * Component API (Handover 0814):
 * - Props: modelValue (Boolean), agent (Object)
 * - Emits: update:modelValue
 * - Orchestrator check: agent.agent_display_name === 'orchestrator'
 * - Regular agents: fetches via templates.list() then templates.preview()
 * - Orchestrator: fetches via system.getOrchestratorPrompt()
 * - Title: "System Orchestrator Prompt" or "Agent Details: {agent_name}"
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentDetailsModal from '@/components/projects/AgentDetailsModal.vue'
import api from '@/services/api'

// Mock the agentColors config -- only getAgentColor's return shape is faked;
// getAgentColorKey/getAgentInitials (FE-9490) keep their REAL implementation
// via importOriginal, since AgentDetailsModal now delegates to them directly.
vi.mock('@/config/agentColors', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    getAgentColor: () => ({ hex: '#4a90d9' }),
  }
})

describe('AgentDetailsModal Component', () => {
  let vuetify

  beforeEach(() => {
    vuetify = createVuetify({
      components,
      directives,
    })
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  const createWrapper = (props = {}, options = {}) => {
    return mount(AgentDetailsModal, {
      props: {
        modelValue: true,
        agent: {
          id: 'agent-job-123',
          agent_id: 'agent-job-123',
          agent_display_name: 'implementer',
          agent_name: 'Test Implementer',
          template_id: 'template-456',
          ...props.agent,
        },
        ...props,
      },
      global: {
        plugins: [vuetify],
        stubs: {
          'v-dialog': {
            template: '<div class="v-dialog" v-if="modelValue"><slot /></div>',
            props: ['modelValue'],
          },
          ...options.stubs,
        },
      },
    })
  }

  describe('Dialog Visibility', () => {
    it('renders dialog when modelValue is true', () => {
      // Prevent API call from failing
      api.templates.list.mockResolvedValue({ data: [] })
      api.templates.preview.mockResolvedValue({ data: { preview: 'test' } })

      const wrapper = createWrapper({ modelValue: true })

      expect(wrapper.find('.v-dialog').exists()).toBe(true)
      // Title is "Agent Details: {agent_name}" for non-orchestrator
      expect(wrapper.text()).toContain('Agent Details')
    })

    it('does not render dialog content when modelValue is false', () => {
      const wrapper = createWrapper({ modelValue: false })

      // Dialog content should not be visible when closed
      const cardText = wrapper.find('.v-card-text')
      if (cardText.exists()) {
        expect(wrapper.find('.v-dialog--active').exists()).toBe(false)
      }
    })

    it('emits update:modelValue when dialog is closed', async () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper()

      // Find close button
      const buttons = wrapper.findAll('button')
      const closeBtn = buttons.find((btn) => btn.text().includes('Close'))

      if (closeBtn) {
        await closeBtn.trigger('click')
        expect(wrapper.emitted('update:modelValue')).toBeTruthy()
        expect(wrapper.emitted('update:modelValue')[0]).toEqual([false])
      }
    })
  })

  describe('Agent Information Display', () => {
    it('displays agent name in dialog title', () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper({
        agent: {
          agent_name: 'Custom Tester Agent',
          agent_display_name: 'tester',
        },
      })

      // Title format: "Agent Details: {agent_name}"
      expect(wrapper.text()).toContain('Custom Tester Agent')
    })

    it('displays agent display name badge', () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          agent_name: 'Test Agent',
        },
      })

      // Component shows agent_display_name in a chip
      expect(wrapper.text()).toContain('implementer')
    })

    it('displays agent ID', () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper({
        agent: {
          id: 'job-abc-123',
          agent_id: 'job-abc-123',
          agent_display_name: 'tester',
          agent_name: 'Test Agent',
        },
      })

      expect(wrapper.text()).toContain('job-abc-123')
    })
  })

  describe('Regular Agent Template Display', () => {
    beforeEach(() => {
      // Mock templates.list response (used to find template by name)
      api.templates.list.mockResolvedValue({
        data: [
          {
            id: 'template-456',
            name: 'Implementer Template',
            role: 'implementer',
          },
        ],
      })

      // Mock templates.preview response
      api.templates.preview.mockResolvedValue({
        data: {
          preview: 'Generated preview content for agent\n\nProject: Test Project',
        },
      })
    })

    it('fetches template data for non-orchestrator agents', async () => {
      createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      await flushPromises()

      // Component uses templates.preview for template content
      expect(api.templates.preview).toHaveBeenCalledWith('template-456', {})
    })

    it('displays preview content in monospace font', async () => {
      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      await flushPromises()

      // Template content should be in a pre element
      const preElements = wrapper.findAll('pre')
      expect(preElements.length).toBeGreaterThan(0)
    })

    it('displays preview content text', async () => {
      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      await flushPromises()

      expect(wrapper.text()).toContain('Generated preview content')
    })

    it('shows loading state while fetching template', async () => {
      let resolveFunc
      api.templates.preview.mockImplementation(
        () => new Promise((resolve) => { resolveFunc = resolve })
      )

      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      // Wait for watcher to trigger
      await flushPromises()

      // Should show loading indicator
      expect(wrapper.text()).toContain('Loading')

      // Cleanup: resolve promise
      if (resolveFunc) resolveFunc({ data: { preview: '' } })
      await flushPromises()
    })

    it('handles template fetch error gracefully', async () => {
      api.templates.preview.mockRejectedValue(new Error('Failed to fetch template'))

      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      await flushPromises()

      expect(wrapper.text()).toContain('Failed to load')
    })

    it('handles missing template_id by searching templates list', async () => {
      createWrapper({
        agent: {
          agent_display_name: 'implementer',
          agent_name: 'Implementer',
          template_id: null,
        },
      })

      await flushPromises()

      // Without template_id, component searches templates.list by name
      expect(api.templates.list).toHaveBeenCalled()
    })
  })

  describe('Orchestrator Prompt Display', () => {
    beforeEach(() => {
      // Mock orchestrator prompt response
      api.system.getOrchestratorPrompt.mockResolvedValue({
        data: {
          content:
            'You are the System Orchestrator...\n\nCoordinate all agents and manage workflow.',
        },
      })
    })

    it('fetches orchestrator prompt for orchestrator agent type', async () => {
      createWrapper({
        agent: {
          agent_display_name: 'orchestrator',
          agent_name: 'System Orchestrator',
        },
      })

      await flushPromises()

      expect(api.system.getOrchestratorPrompt).toHaveBeenCalled()
    })

    it('displays orchestrator prompt in monospace font', async () => {
      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'orchestrator',
        },
      })

      await flushPromises()

      // Check for template content element with class
      const contentCard = wrapper.find('.template-content-card')
      expect(contentCard.exists()).toBe(true)

      const preElement = contentCard.find('pre.template-content')
      expect(preElement.exists()).toBe(true)
      expect(wrapper.text()).toContain('You are the System Orchestrator')
    })

    it('shows specific title for orchestrator', async () => {
      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'orchestrator',
          agent_name: 'System Orchestrator',
        },
      })

      await flushPromises()

      expect(wrapper.text()).toContain('System Orchestrator Prompt')
    })

    it('handles orchestrator prompt fetch error', async () => {
      api.system.getOrchestratorPrompt.mockRejectedValue(
        new Error('Failed to fetch orchestrator prompt')
      )

      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'orchestrator',
        },
      })

      await flushPromises()

      expect(wrapper.text()).toContain('Failed to load')
    })
  })

  describe('Content Display Formatting', () => {
    beforeEach(() => {
      api.templates.preview.mockResolvedValue({
        data: {
          preview:
            'Line 1\nLine 2\nLine 3\n\n# Section\n\nMore content with **markdown**',
        },
      })
    })

    it('preserves whitespace and line breaks in template content', async () => {
      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      await flushPromises()

      // Check if pre element exists in the content card
      const contentCard = wrapper.find('.template-content-card')
      expect(contentCard.exists()).toBe(true)

      // Pre element should be within the content card
      const preElement = contentCard.find('pre.template-content')
      expect(preElement.exists()).toBe(true)
    })

    it('displays content as read-only', async () => {
      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      await flushPromises()

      // Should not have any textarea or editable inputs for content
      const textareas = wrapper.findAll('textarea')
      const editableInputs = textareas.filter((ta) =>
        ta.attributes('readonly') === undefined || ta.attributes('readonly') === 'false'
      )
      expect(editableInputs.length).toBe(0)
    })
  })

  describe('Modal Styling and Theme', () => {
    it('applies dialog styling', () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper()

      const dialog = wrapper.find('.v-dialog')
      expect(dialog.exists()).toBe(true)
    })

    it('has proper max width for readability', () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper()

      // Modal should have reasonable max-width (800px as per component)
      expect(wrapper.html()).toContain('max-width')
    })

    it('includes close button', () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper()

      const buttons = wrapper.findAll('button')
      const closeBtn = buttons.find((btn) => btn.text().includes('Close'))
      expect(closeBtn).toBeTruthy()
    })
  })

  describe('Edge Cases', () => {
    it('handles null agent gracefully', () => {
      const wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: null,
        },
        global: {
          plugins: [vuetify],
          stubs: {
            'v-dialog': {
              template: '<div class="v-dialog" v-if="modelValue"><slot /></div>',
              props: ['modelValue'],
            },
          },
        },
      })

      expect(wrapper.exists()).toBe(true)
      // Should show warning message
      expect(wrapper.text()).toContain('No agent information')
    })

    it('handles empty preview content', async () => {
      api.templates.preview.mockResolvedValue({
        data: {
          preview: null,
        },
      })

      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      await flushPromises()

      // Empty/null content should show fallback text
      expect(wrapper.text()).toContain('No template information available')
    })
  })

  describe('Accessibility', () => {
    it('has proper dialog title', () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper()

      expect(wrapper.text()).toContain('Agent Details')
    })

    it('has close button in header', () => {
      api.templates.list.mockResolvedValue({ data: [] })

      const wrapper = createWrapper()

      const closeBtn = wrapper.find('button.dlg-close')
      expect(closeBtn.exists()).toBe(true)
    })

    it('loading state is announced', async () => {
      let resolveFunc
      api.templates.preview.mockImplementation(
        () => new Promise((resolve) => { resolveFunc = resolve })
      )

      const wrapper = createWrapper({
        agent: {
          agent_display_name: 'implementer',
          template_id: 'template-456',
        },
      })

      // Wait for watcher to trigger
      await flushPromises()

      // Loading should be visible while promise is pending
      expect(wrapper.text()).toContain('Loading')

      // Cleanup: resolve promise
      if (resolveFunc) resolveFunc({ data: { preview: '' } })
      await flushPromises()
    })
  })

})
