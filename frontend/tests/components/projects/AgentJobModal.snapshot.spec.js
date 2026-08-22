/**
 * AgentJobModal.snapshot.spec.js - Handover 0818 Phase 3
 *
 * Tests for the snapshot pattern that decouples the AgentJobModal
 * from live WebSocket reactivity. When the modal opens, it takes a
 * shallow clone of the agent prop. While open, computed properties
 * (todoItems, formattedCreatedAt) read from the snapshot instead of
 * the live prop, preventing WebSocket-driven reference changes from
 * causing re-renders that reset user interaction state.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AgentJobModal from '@/components/projects/AgentJobModal.vue'

// Mock agentColors config -- only getAgentColor's return shape is faked (a
// fixed, easy-to-assert-on hex); getAgentColorKey/getAgentInitials (FE-9490)
// keep their REAL implementation via importOriginal so the badge-key and
// initials logic under test is the actual production code, not a stand-in.
vi.mock('@/config/agentColors', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    getAgentColor: (name) => ({
      hex: name ? '#4CAF50' : '#757575',
    }),
  }
})

const createMockAgent = (overrides = {}) => ({
  job_id: 'job-300',
  agent_id: 'agent-400',
  agent_name: 'architect',
  agent_display_name: 'System Architect',
  mission: 'Design the API layer',
  created_at: '2026-03-14T09:00:00Z',
  todo_items: [
    { content: 'Define schema', status: 'completed' },
    { content: 'Create endpoints', status: 'in_progress' },
    { content: 'Write docs', status: 'pending' },
  ],
  ...overrides,
})

function mountModal(propsData = {}) {
  return mount(AgentJobModal, {
    props: {
      show: false,
      agent: createMockAgent(),
      ...propsData,
    },
    global: {
      directives: { draggable: () => {} },
      stubs: {
        'v-dialog': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'v-card-title': { template: '<div class="v-card-title"><slot /></div>' },
        'v-card-text': { template: '<div class="v-card-text"><slot /></div>' },
        'v-card-actions': { template: '<div><slot /></div>' },
        'v-divider': { template: '<hr />' },
        'v-icon': { template: '<span class="v-icon"><slot /></span>' },
        'v-btn': { template: '<button class="v-btn"><slot /></button>' },
        'v-avatar': { template: '<div class="v-avatar"><slot /></div>' },
        'v-spacer': { template: '<div />' },
        'v-tabs': { template: '<div><slot /></div>' },
        'v-tab': { template: '<div><slot /></div>' },
        'v-window': { template: '<div><slot /></div>' },
        'v-window-item': { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('AgentJobModal snapshot pattern (Handover 0818 Phase 3)', () => {
  let wrapper

  beforeEach(() => {
    vi.clearAllMocks()
    if (wrapper) wrapper.unmount()
  })

  it('todo items show snapshot data when agent prop changes while open', async () => {
    const originalAgent = createMockAgent({
      todo_items: [
        { content: 'Original task A', status: 'pending' },
        { content: 'Original task B', status: 'in_progress' },
      ],
    })

    wrapper = mountModal({ show: false, agent: originalAgent })

    // Open the modal (triggers snapshot)
    await wrapper.setProps({ show: true })
    await flushPromises()

    // Verify initial snapshot todo items
    expect(wrapper.vm.todoItems).toHaveLength(2)
    expect(wrapper.vm.todoItems[0].content).toBe('Original task A')

    // Simulate WebSocket update with different todo_items (new object reference)
    const updatedAgent = createMockAgent({
      todo_items: [
        { content: 'Updated task X', status: 'completed' },
        { content: 'Updated task Y', status: 'completed' },
        { content: 'Updated task Z', status: 'pending' },
      ],
    })
    await wrapper.setProps({ agent: updatedAgent })
    await flushPromises()

    // Todo items should still reflect the snapshot (original data), not the updated prop
    expect(wrapper.vm.todoItems).toHaveLength(2)
    expect(wrapper.vm.todoItems[0].content).toBe('Original task A')
  })

  it('active tab persists when agent prop changes while open', async () => {
    wrapper = mountModal({
      show: false,
      agent: createMockAgent(),
      initialTab: 'plan',
    })

    // Open the modal
    await wrapper.setProps({ show: true })
    await flushPromises()

    // Should start on plan tab
    expect(wrapper.vm.activeTab).toBe('plan')

    // Simulate WebSocket update (new agent reference)
    const newRef = createMockAgent({ _wsUpdate: true })
    await wrapper.setProps({ agent: newRef })
    await flushPromises()

    // Tab should remain on plan -- the snapshot prevents reactivity cascade
    expect(wrapper.vm.activeTab).toBe('plan')
  })

  it('closing and reopening takes fresh snapshot', async () => {
    const agent1 = createMockAgent({
      todo_items: [{ content: 'Phase 1 task', status: 'pending' }],
    })

    wrapper = mountModal({ show: false, agent: agent1 })

    // Open the modal
    await wrapper.setProps({ show: true })
    await flushPromises()

    // Verify first snapshot
    expect(wrapper.vm.todoItems).toHaveLength(1)
    expect(wrapper.vm.todoItems[0].content).toBe('Phase 1 task')
    expect(wrapper.vm.agentSnapshot).not.toBeNull()

    // Close the modal
    await wrapper.setProps({ show: false })
    await flushPromises()

    // Snapshot should be cleared
    expect(wrapper.vm.agentSnapshot).toBeNull()

    // Reopen with updated agent
    const agent2 = createMockAgent({
      todo_items: [
        { content: 'Phase 2 task A', status: 'in_progress' },
        { content: 'Phase 2 task B', status: 'pending' },
      ],
    })
    await wrapper.setProps({ agent: agent2, show: true })
    await flushPromises()

    // Should reflect new snapshot data
    expect(wrapper.vm.todoItems).toHaveLength(2)
    expect(wrapper.vm.todoItems[0].content).toBe('Phase 2 task A')
  })
})
