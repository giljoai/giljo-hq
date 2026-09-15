import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import JobsBoardAgentRow from './JobsBoardAgentRow.vue'

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

function mountRow(agent, now = Date.parse('2026-08-30T12:00:00Z')) {
  return mount(JobsBoardAgentRow, {
    props: { agent, now },
    global: { stubs: { 'v-tooltip': tooltipStub } },
  })
}

describe('JobsBoardAgentRow', () => {
  it('renders exactly badge, steps, duration, status, messages -- no visible name text', () => {
    const wrapper = mountRow({
      agent_id: 'e8312b95-4c1a-4f7e-b3d2-77a9e1c0d4f8',
      job_id: '69760e9d-2b11-4a03-9c5e-1f2d3a4b5c6d',
      agent_display_name: 'implementer',
      agent_name: 'implementer-backend',
      status: 'working',
      steps: { completed: 3, total: 4 },
      duration_seconds: 41,
      messages_waiting_count: 1,
    })

    expect(wrapper.find('[data-testid="jb-agent-badge"]').text()).toBe('IM')
    expect(wrapper.find('[data-testid="jb-agent-steps"]').text()).toContain('3')
    expect(wrapper.find('[data-testid="jb-agent-steps"]').text()).toContain('/4')
    expect(wrapper.find('[data-testid="jb-agent-status"]').text()).toBe('Working')
    expect(wrapper.find('[data-testid="jb-agent-messages"]').text()).toBe('1')
    expect(wrapper.find('[data-testid="jb-agent-row"]').text()).not.toContain('implementer-backend')
  })

  it('shows "—" for steps when no numeric steps summary is present', () => {
    const wrapper = mountRow({ agent_display_name: 'orchestrator', status: 'staged' })
    expect(wrapper.find('[data-testid="jb-agent-steps"]').text()).toBe('—')
  })

  it('tints the messages pill using the shared .msg-badge classes, zero vs has-msgs', () => {
    const zero = mountRow({ agent_display_name: 'tester', status: 'complete', messages_waiting_count: 0 })
    expect(zero.find('[data-testid="jb-agent-messages"]').classes()).toContain('msg-badge')
    expect(zero.find('[data-testid="jb-agent-messages"]').classes()).toContain('zero')

    const nonZero = mountRow({ agent_display_name: 'tester', status: 'complete', messages_waiting_count: 2 })
    expect(nonZero.find('[data-testid="jb-agent-messages"]').classes()).toContain('msg-badge')
    expect(nonZero.find('[data-testid="jb-agent-messages"]').classes()).toContain('has-msgs')
    expect(nonZero.find('[data-testid="jb-agent-messages"]').classes()).not.toContain('zero')
  })

  it('the hover tooltip carries name, role, agent UUID and job UUID', () => {
    const wrapper = mountRow({
      agent_id: 'e8312b95-4c1a-4f7e-b3d2-77a9e1c0d4f8',
      job_id: '69760e9d-2b11-4a03-9c5e-1f2d3a4b5c6d',
      agent_display_name: 'orchestrator',
      agent_name: 'Orchestrator',
      status: 'working',
    })
    const tooltip = wrapper.find('[data-testid="jb-agent-tooltip"]')
    expect(tooltip.text()).toContain('Orchestrator')
    expect(tooltip.text()).toContain('Fixed System Agent')
    expect(tooltip.text()).toContain('e8312b95-4c1a-4f7e-b3d2-77a9e1c0d4f8')
    expect(tooltip.text()).toContain('69760e9d-2b11-4a03-9c5e-1f2d3a4b5c6d')
  })

  it('uses the shared .agent-badge-sq--sm class instead of a bespoke badge', () => {
    const wrapper = mountRow({ agent_display_name: 'implementer', status: 'working' })
    const badge = wrapper.find('[data-testid="jb-agent-badge"]')
    expect(badge.classes()).toContain('agent-badge-sq')
    expect(badge.classes()).toContain('agent-badge-sq--sm')
  })

  it('never hardcodes a hex color -- badge and status styling resolve through getAgentBadgeStyle/getStatusColor', () => {
    const wrapper = mountRow({ agent_display_name: 'reviewer', status: 'blocked' })
    const badgeStyle = wrapper.find('[data-testid="jb-agent-badge"]').attributes('style')
    expect(badgeStyle).toMatch(/rgba\(/)
  })
})
