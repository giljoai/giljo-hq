/**
 * AgentDetailsModal.0244a.spec.js
 *
 * Handover 0244a: Agent Info Icon Template Display Tests
 *
 * Post-refactor (Handover 0814):
 * The component was simplified to show a rendered template preview (previewContent)
 * instead of individual template fields. Key changes:
 * - Uses agent_display_name (not agent_type) for orchestrator detection
 * - Fetches template via apiClient.templates.preview(templateId, {}) for rendered output
 * - Falls back to name-matching against active templates if no template_id
 * - No expansion panels, no individual field display (role, cli_tool, model, etc.)
 * - No copy buttons in the simplified view
 * - Orchestrator uses apiClient.system.getOrchestratorPrompt()
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentDetailsModal from '@/components/projects/AgentDetailsModal.vue'

// Mock API service
const mockTemplatePreview = vi.fn()
const mockTemplateList = vi.fn()
const mockOrchestratorPrompt = vi.fn()

vi.mock('@/services/api', () => ({
  default: {
    templates: {
      preview: (...args) => mockTemplatePreview(...args),
      list: (...args) => mockTemplateList(...args),
    },
    system: {
      getOrchestratorPrompt: (...args) => mockOrchestratorPrompt(...args),
    }
  }
}))

describe('AgentDetailsModal - Handover 0244a Template Display', () => {
  let vuetify
  let wrapper

  beforeEach(() => {
    vuetify = createVuetify({
      components,
      directives,
    })

    // Reset mocks
    mockTemplatePreview.mockReset()
    mockTemplateList.mockReset()
    mockOrchestratorPrompt.mockReset()
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  describe('1. Template Data Fetching and Display', () => {
    it('fetches and displays template preview for non-orchestrator agents', async () => {
      const previewText = 'You are the implementer agent. Your role is to implement features...'

      mockTemplatePreview.mockResolvedValue({ data: { preview: previewText } })

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'agent-456',
            agent_display_name: 'implementer',
            agent_name: 'Test Implementer',
            template_id: 'template-123'
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      // Wait for async data fetch
      await flushPromises()

      // Verify API was called with correct template_id
      expect(mockTemplatePreview).toHaveBeenCalledWith('template-123', {})

      // Verify preview content is displayed
      expect(wrapper.text()).toContain('implementer')
    })

  })

  describe('3. Orchestrator Functionality (Existing)', () => {
    it('fetches and displays orchestrator prompt', async () => {
      const mockPrompt = {
        content: 'You are the system orchestrator. Coordinate all agents.'
      }

      mockOrchestratorPrompt.mockResolvedValue({ data: mockPrompt })

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'orchestrator-123',
            agent_display_name: 'orchestrator',
            agent_name: 'Orchestrator'
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      await flushPromises()

      // Verify orchestrator prompt API was called
      expect(mockOrchestratorPrompt).toHaveBeenCalled()

      // Verify orchestrator prompt is displayed
      expect(wrapper.text()).toContain('System Orchestrator Prompt')
      expect(wrapper.text()).toContain('You are the system orchestrator')
    })
  })

  describe('4. Graceful Handling of Missing template_id', () => {
    it('displays info message when template_id is null and no name match', async () => {
      // Mock template list returning no matches
      mockTemplateList.mockResolvedValue({ data: [] })

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'agent-456',
            agent_display_name: 'implementer',
            agent_name: 'Test Agent',
            template_id: null
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      await flushPromises()

      // Should attempt name matching via templates.list
      // If no match found, should show no-template info
      expect(wrapper.text()).toContain('No template information available')
    })

    it('displays info message when template_id is undefined and no name match', async () => {
      // Mock template list returning no matches
      mockTemplateList.mockResolvedValue({ data: [] })

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'agent-456',
            agent_display_name: 'implementer',
            agent_name: 'Test Agent'
            // template_id is undefined
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      await flushPromises()

      // Should show no-template info if no match found
      expect(wrapper.text()).toContain('No template information available')
    })
  })

  describe('5. Loading and Error States', () => {
    it('displays loading state while fetching template data', async () => {
      // Mock a delayed response
      mockTemplatePreview.mockImplementation(() =>
        new Promise(resolve => setTimeout(() => resolve({ data: { preview: 'test' } }), 100))
      )

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'agent-456',
            agent_display_name: 'implementer',
            template_id: 'template-123'
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      // Check loading state immediately
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('Loading...')
    })

    it('displays error message when template fetch fails', async () => {
      mockTemplatePreview.mockRejectedValue({
        response: {
          data: {
            error_code: 'RESOURCE_NOT_FOUND',
            message: 'Template not found'
          }
        }
      })

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'agent-456',
            agent_display_name: 'implementer',
            template_id: 'template-123'
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      await flushPromises()

      // Verify error message is displayed
      expect(wrapper.text()).toContain('Failed to load')
      expect(wrapper.text()).toContain('Template not found')
    })

    it('displays generic error when API error has no response', async () => {
      mockTemplatePreview.mockRejectedValue(new Error('Network error'))

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'agent-456',
            agent_display_name: 'implementer',
            template_id: 'template-123'
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      await flushPromises()

      // Verify error message is displayed
      expect(wrapper.text()).toContain('Failed to load')
      expect(wrapper.text()).toContain('Network error')
    })
  })

  describe('6. Dialog Title and Agent Type Detection', () => {
    it('displays correct title for orchestrator', async () => {
      mockOrchestratorPrompt.mockResolvedValue({ data: { content: 'test' } })

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'orchestrator-123',
            agent_display_name: 'orchestrator',
            agent_name: 'Orchestrator'
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      await flushPromises()

      expect(wrapper.text()).toContain('System Orchestrator Prompt')
    })

    it('displays correct title for non-orchestrator agent', async () => {
      mockTemplatePreview.mockResolvedValue({ data: { preview: 'test content' } })

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'agent-456',
            agent_display_name: 'implementer',
            agent_name: 'Test Implementer',
            template_id: 'template-123'
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      await flushPromises()

      expect(wrapper.text()).toContain('Agent Details: Test Implementer')
    })
  })

  describe('8. Agent Type Color Coding', () => {
    it('displays agent display name chip', async () => {
      mockTemplatePreview.mockResolvedValue({ data: { preview: 'test content' } })

      wrapper = mount(AgentDetailsModal, {
        props: {
          modelValue: true,
          agent: {
            id: 'agent-456',
            agent_display_name: 'tester',
            agent_name: 'Test Tester',
            template_id: 'template-123'
          }
        },
        global: {
          plugins: [vuetify]
        }
      })

      await flushPromises()

      // Verify agent display name chip is displayed
      expect(wrapper.text()).toContain('tester')
    })
  })
})
