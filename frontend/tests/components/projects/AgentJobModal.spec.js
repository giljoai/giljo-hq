/**
 * AgentJobModal.spec.js - Handover 0423
 *
 * Tests for the AgentJobModal component that displays job mission and plan tabs.
 * This modal was created to separate TODO/plan visualization from MessageAuditModal.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentJobModal from '@/components/projects/AgentJobModal.vue'
import { getAgentInitials } from '@/config/agentColors'

const vuetify = createVuetify({
  components,
  directives,
})

const createMockAgent = (overrides = {}) => ({
  job_id: 'job-123',
  agent_id: 'agent-456',
  agent_name: 'implementer',
  agent_display_name: 'Code Implementer',
  mission: 'Implement feature X',
  todo_items: [],
  ...overrides,
})

describe('AgentJobModal', () => {
  let wrapper

  beforeEach(() => {
    // Clean up any existing wrapper
    if (wrapper) {
      wrapper.unmount()
    }
  })

  describe('Component rendering', () => {
    it('should render when show prop is true', () => {
      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent: createMockAgent(),
        },
        global: {
          plugins: [vuetify],
        },
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should emit close event when handleClose is called', () => {
      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent: createMockAgent(),
        },
        global: {
          plugins: [vuetify],
        },
      })

      wrapper.vm.handleClose()
      expect(wrapper.emitted()).toHaveProperty('close')
    })
  })

  describe('Computed properties', () => {
    it('should compute todoItems from agent prop', () => {
      const agent = createMockAgent({
        todo_items: [
          { content: 'Task 1', status: 'pending' },
          { content: 'Task 2', status: 'in_progress' },
        ],
      })

      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent,
        },
        global: {
          plugins: [vuetify],
        },
      })

      expect(wrapper.vm.todoItems).toEqual(agent.todo_items)
      expect(wrapper.vm.todoItemsCount).toBe(2)
    })

    it('should return empty array when agent has no todo_items', () => {
      const agent = createMockAgent({
        todo_items: null,
      })

      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent,
        },
        global: {
          plugins: [vuetify],
        },
      })

      expect(wrapper.vm.todoItems).toEqual([])
      expect(wrapper.vm.todoItemsCount).toBe(0)
    })
  })

  describe('Helper functions - status icons', () => {
    beforeEach(() => {
      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent: createMockAgent(),
        },
        global: {
          plugins: [vuetify],
        },
      })
    })

    it('should return correct icon for pending status', () => {
      expect(wrapper.vm.getStatusIcon('pending')).toBe('mdi-checkbox-blank-outline')
    })

    it('should return correct icon for in_progress status', () => {
      expect(wrapper.vm.getStatusIcon('in_progress')).toBe('mdi-progress-clock')
    })

    it('should return correct icon for completed status', () => {
      expect(wrapper.vm.getStatusIcon('completed')).toBe('mdi-checkbox-marked')
    })

    it('should return default icon for unknown status', () => {
      expect(wrapper.vm.getStatusIcon('unknown')).toBe('mdi-checkbox-blank-outline')
    })
  })

  describe('Helper functions - status colors', () => {
    beforeEach(() => {
      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent: createMockAgent(),
        },
        global: {
          plugins: [vuetify],
        },
      })
    })

    it('should return correct color for pending status', () => {
      expect(wrapper.vm.getStatusColor('pending')).toBe('grey')
    })

    it('should return correct color for in_progress status', () => {
      expect(wrapper.vm.getStatusColor('in_progress')).toBe('warning')
    })

    it('should return correct color for completed status', () => {
      expect(wrapper.vm.getStatusColor('completed')).toBe('success')
    })

    it('should return default color for unknown status', () => {
      expect(wrapper.vm.getStatusColor('unknown')).toBe('grey')
    })
  })

  describe('Helper functions - agent avatar', () => {
    beforeEach(() => {
      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent: createMockAgent(),
        },
        global: {
          plugins: [vuetify],
        },
      })
    })

    it('should return a badge style for agent name', () => {
      const style = wrapper.vm.getAgentBadgeStyle('test-agent')
      expect(style).toHaveProperty('backgroundColor')
      expect(style).toHaveProperty('color')
      expect(style.color).toMatch(/^#[0-9A-F]{6}$/i) // Valid hex color
    })

    it('should return default badge style for null agent name', () => {
      const style = wrapper.vm.getAgentBadgeStyle(null)
      expect(style.color).toBe('#D4B08A')
    })

    // FE-9490: AgentJobModal's own initials splitter (map(word => word[0]) over
    // the WHOLE split, no punctuation stripped) was one of six copy-pasted
    // duplicates and was removed in favour of the shared getAgentInitials()
    // (frontend/src/config/agentColors.js) that every badge site now calls —
    // see AgentJobModal.vue's template, which now calls it directly instead of
    // a local getAgentAbbr. These assertions exercise that same shared helper,
    // and their expected values are the CORRECTED shape (two-char single-word
    // and '??' fallback), matching the convention every other badge site
    // already used before this consolidation.
    it('should return abbreviation for agent name', () => {
      expect(getAgentInitials('test-agent')).toBe('TA')
      expect(getAgentInitials('code_implementer')).toBe('CI')
      expect(getAgentInitials('single')).toBe('SI') // Single word -> first two chars (shared convention)
    })

    it('should return default abbreviation for null agent name', () => {
      expect(getAgentInitials(null)).toBe('??')
    })
  })

  describe('Tab switching', () => {
    it('should default to mission tab', () => {
      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent: createMockAgent(),
        },
        global: {
          plugins: [vuetify],
        },
      })

      expect(wrapper.vm.activeTab).toBe('mission')
    })

    it('should initialize to plan tab when initialTab is "plan"', () => {
      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent: createMockAgent(),
          initialTab: 'plan',
        },
        global: {
          plugins: [vuetify],
        },
      })

      expect(wrapper.vm.activeTab).toBe('plan')
    })

    it('should update activeTab when initialTab prop changes', async () => {
      wrapper = mount(AgentJobModal, {
        props: {
          show: true,
          agent: createMockAgent(),
          initialTab: 'mission',
        },
        global: {
          plugins: [vuetify],
        },
      })

      expect(wrapper.vm.activeTab).toBe('mission')

      await wrapper.setProps({ initialTab: 'plan' })
      expect(wrapper.vm.activeTab).toBe('plan')
    })
  })
})
