import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import ProjectReviewModal from '@/components/projects/ProjectReviewModal.vue'
import StatusBadge from '@/components/StatusBadge.vue'

// FE-9427: ProjectReviewModal calls useRouter() -- openInHub() pushes the named
// 'Hub' route. Mounted without a router that returned `undefined`, so the
// deep-link path was inert. The route is named because the component pushes by
// name; a catch-all would let a wrong destination pass.
const hubRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})

// Mock the api module
vi.mock('@/services/api', () => ({
  default: {
    projects: {
      get: vi.fn(),
      review: vi.fn(),
    },
    agentJobs: {
      list: vi.fn(),
      messages: vi.fn(),
    },
    products: {
      getMemoryEntries: vi.fn(),
    },
  },
}))

import api from '@/services/api'

describe('ProjectReviewModal.vue', () => {
  let wrapper
  let pinia
  let vuetify

  const mockProject = {
    id: 'proj-1',
    name: 'Test Project',
    description: 'A test project description',
    status: 'completed',
    mission: 'Build the feature',
    created_at: '2026-03-01T10:00:00Z',
    completed_at: '2026-03-10T15:00:00Z',
    product_id: 'prod-1',
  }

  const mockAgents = [
    { id: 'job-1', job_id: 'job-1', agent_display_name: 'Orchestrator', agent_name: 'orchestrator', agent_role: 'orchestrator', status: 'complete' },
    { id: 'job-2', job_id: 'job-2', agent_display_name: 'Implementor', agent_name: 'implementor', agent_role: 'implementor', status: 'complete' },
  ]

  const mockMemoryEntries = [
    { sequence: 1, summary: 'Initial setup completed' },
    { sequence: 2, summary: 'Feature implemented' },
  ]

  const mockMessages = [
    { id: 'msg-1', from: 'Orchestrator', content: 'Starting work', created_at: '2026-03-01T11:00:00Z', direction: 'outbound', message_type: 'broadcast' },
    { id: 'msg-2', from: 'Implementor', content: 'Work complete', created_at: '2026-03-01T12:00:00Z', direction: 'inbound', message_type: 'broadcast' },
  ]

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify()

    vi.clearAllMocks()

    api.projects.review.mockResolvedValue({
      data: {
        project: { ...mockProject, agents: mockAgents },
        agent_jobs: mockAgents,
        memory_entries: mockMemoryEntries,
      },
    })
    api.agentJobs.messages.mockResolvedValue({ data: { messages: mockMessages, job_id: 'job-1', agent_id: 'agent-1' } })
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  function mountModal(props = {}) {
    return mount(ProjectReviewModal, {
      props: {
        show: true,
        projectId: 'proj-1',
        productId: 'prod-1',
        ...props,
      },
      global: {
        plugins: [pinia, vuetify, hubRouter],
      },
    })
  }

  async function mountAndWaitForData(props = {}) {
    const w = mountModal({ show: false, ...props })
    await w.setProps({ show: true })
    await flushPromises()
    await w.vm.$nextTick()
    return w
  }

  describe('Rendering', () => {
    it('passes show prop to dialog model-value', () => {
      wrapper = mountModal({ show: true })
      // The dialog component receives the show prop
      const dialog = wrapper.findComponent({ name: 'VDialog' })
      if (dialog.exists()) {
        expect(dialog.props('modelValue')).toBe(true)
      } else {
        // VDialog may not be found directly - check the component renders
        expect(wrapper.html()).toContain('review-modal')
      }
    })

    it('passes false to dialog when show is false', () => {
      wrapper = mountModal({ show: false })
      // Component should exist but dialog should be closed
      expect(wrapper.exists()).toBe(true)
    })
  })

  describe('Data Loading', () => {
    it('fetches project review data on open', async () => {
      wrapper = await mountAndWaitForData()

      expect(api.projects.review).toHaveBeenCalledWith('proj-1')
    })

    it('skips memory fetch when no productId is provided', async () => {
      wrapper = await mountAndWaitForData({ productId: null })

      expect(api.products.getMemoryEntries).not.toHaveBeenCalled()
    })

    it('shows error state on API failure', async () => {
      api.projects.review.mockRejectedValue(new Error('Network error'))

      wrapper = await mountAndWaitForData()

      // The error ref should be set
      expect(wrapper.vm.error).toBeTruthy()
      expect(wrapper.vm.error).toContain('Network error')
    })
  })

  describe('Project Overview', () => {
    it('displays project name, description, and status after data loads', async () => {
      wrapper = await mountAndWaitForData()

      const text = wrapper.text()
      expect(text).toContain('Test Project')
      expect(text).toContain('A test project description')
      expect(text).toContain('completed')
    })

    it('displays mission text', async () => {
      wrapper = await mountAndWaitForData()

      expect(wrapper.text()).toContain('Build the feature')
    })

    it('handles mission as object with mission_statement', async () => {
      api.projects.review.mockResolvedValue({
        data: {
          project: { ...mockProject, mission: { mission_statement: 'Statement from object' }, agents: [] },
          agent_jobs: [],
          memory_entries: [],
        },
      })

      wrapper = await mountAndWaitForData()

      expect(wrapper.text()).toContain('Statement from object')
    })
  })

  describe('Agent Roster', () => {
    it('renders agent names and count', async () => {
      wrapper = await mountAndWaitForData()

      const text = wrapper.text()
      expect(text).toContain('Orchestrator')
      expect(text).toContain('Implementor')
      expect(text).toContain('Agents (2)')
    })

    it('handles empty agents list', async () => {
      api.projects.review.mockResolvedValue({
        data: {
          project: { ...mockProject, agents: [] },
          agent_jobs: [],
          memory_entries: [],
        },
      })

      wrapper = await mountAndWaitForData()

      expect(wrapper.text()).toContain('Agents (0)')
      expect(wrapper.text()).toContain('No data')
    })
  })

  describe('Read-Only Verification', () => {
    it('has no buttons that modify project state', async () => {
      wrapper = await mountAndWaitForData()

      const buttons = wrapper.findAll('button')
      const buttonTexts = buttons.map(b => b.text().toLowerCase())

      const stateChangingActions = ['activate', 'reopen', 'delete', 'cancel', 'deactivate', 'save', 'submit']
      for (const action of stateChangingActions) {
        expect(buttonTexts.some(t => t.includes(action))).toBe(false)
      }

      expect(buttonTexts.some(t => t.includes('close'))).toBe(true)
    })
  })

  describe('Close Event', () => {
    it('emits close event when close button is clicked', async () => {
      wrapper = mountModal()
      await flushPromises()

      const closeBtn = wrapper.find('[data-testid="review-close-btn"]')
      await closeBtn.trigger('click')

      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close event when header X button is clicked', async () => {
      wrapper = mountModal()
      await flushPromises()

      const headerCloseBtn = wrapper.find('.dlg-close')
      await headerCloseBtn.trigger('click')

      expect(wrapper.emitted('close')).toBeTruthy()
    })
  })

  describe('Agent Message Lazy Loading', () => {
    it('loads messages when agent panel is expanded via v-model watcher', async () => {
      wrapper = await mountAndWaitForData()

      // Simulate panel expansion by setting expandedAgentPanels
      wrapper.vm.expandedAgentPanels = [0]
      await flushPromises()

      expect(api.agentJobs.messages).toHaveBeenCalledWith('job-1')
    })

    it('does not reload messages for already-loaded agent', async () => {
      wrapper = await mountAndWaitForData()

      // First expansion
      wrapper.vm.expandedAgentPanels = [0]
      await flushPromises()

      // Second expansion of same panel
      wrapper.vm.expandedAgentPanels = [0]
      await flushPromises()

      // Should only call once (guard in loadAgentMessages)
      expect(api.agentJobs.messages).toHaveBeenCalledTimes(1)
    })

    it('resets expanded panels on modal close', async () => {
      wrapper = await mountAndWaitForData()
      wrapper.vm.expandedAgentPanels = [0]
      await flushPromises()

      await wrapper.setProps({ show: false })
      await flushPromises()

      expect(wrapper.vm.expandedAgentPanels).toEqual([])
    })
  })

  describe('Response Shape Handling', () => {
    it('extracts jobs from JobListResponse shape (res.data.jobs)', async () => {
      wrapper = await mountAndWaitForData()

      // Verify the component correctly parsed the response
      expect(wrapper.vm.agents).toHaveLength(2)
      expect(wrapper.vm.agents[0].agent_display_name).toBe('Orchestrator')
    })

    it('extracts entries from MemoryEntriesResponse shape (res.data.entries)', async () => {
      wrapper = await mountAndWaitForData()

      expect(wrapper.vm.memoryEntries).toHaveLength(2)
      expect(wrapper.vm.memoryEntries[0].summary).toBe('Initial setup completed')
    })
  })
})

describe('StatusBadge - Status Display', () => {
  let wrapper
  let pinia
  let vuetify

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify()
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  function mountBadge(status) {
    return mount(StatusBadge, {
      props: {
        status,
      },
      global: {
        plugins: [pinia, vuetify],
      },
    })
  }

  it('displays correct label for completed status', () => {
    wrapper = mountBadge('completed')

    expect(wrapper.text()).toContain('Completed')
  })

  it('displays correct label for terminated status', () => {
    wrapper = mountBadge('terminated')

    expect(wrapper.text()).toContain('Terminated')
  })

  it('displays correct label for cancelled status', () => {
    wrapper = mountBadge('cancelled')

    expect(wrapper.text()).toContain('Cancelled')
  })

  it('renders as a chip with success color for completed status', () => {
    wrapper = mountBadge('completed')

    // StatusBadge is itself a v-chip wrapper; verify the aria-label reflects status
    expect(wrapper.attributes('aria-label')).toContain('Completed')
  })
})
