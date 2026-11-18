import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import JobsBoardAgentRow from './JobsBoardAgentRow.vue'

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

function mountRow(agent, props = {}) {
  return mount(JobsBoardAgentRow, {
    props: { agent, now: Date.parse('2026-08-30T12:00:00Z'), ...props },
    global: { stubs: { 'v-tooltip': tooltipStub, 'v-menu': true } },
  })
}

describe('JobsBoardAgentRow (FE-9681)', () => {
  it('a waiting agent nobody started reads "Not picked up" and keeps its play control', () => {
    const agent = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'waiting', not_picked_up: true }
    const wrapper = mountRow(agent, { interactive: true, showCopy: true })
    const status = wrapper.find('[data-testid="jb-agent-status"]')
    expect(status.text()).toBe('Not picked up')
    expect(status.attributes('title')).toMatch(/nobody started this agent/i)
    expect(wrapper.find('[data-testid="jb-agent-play"]').exists()).toBe(true)
  })

  it('a waiting agent that is simply waiting reads Waiting', () => {
    const agent = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'waiting' }
    expect(mountRow(agent).find('[data-testid="jb-agent-status"]').text()).toBe('Waiting.')
  })

  it('clicking the steps on a live row opens the agent job on its task list', async () => {
    const agent = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'working', steps: { completed: 2, total: 6 } }
    const wrapper = mountRow(agent, { interactive: true })
    await wrapper.find('[data-testid="jb-agent-steps"]').trigger('click')
    expect(wrapper.emitted('steps')?.[0]?.[0]).toEqual(agent)
  })
})

describe('JobsBoardAgentRow monitoring (FE-0062)', () => {
  const orchestrator = { agent_id: 'a-or', job_id: 'j-or', agent_display_name: 'orchestrator', status: 'working' }

  it('a working orchestrator the card marks as monitoring reads Monitoring, not Not picked up or Working', () => {
    const status = mountRow(orchestrator, { interactive: true, monitoring: true }).find('[data-testid="jb-agent-status"]')
    expect(status.text()).toBe('Monitoring')
  })

  it('without the card marking it, a working orchestrator keeps its own word', () => {
    expect(mountRow(orchestrator, { interactive: true }).find('[data-testid="jb-agent-status"]').text()).toMatch(/^Working/)
  })

  it('monitoring never overrides a stall: a waiting unopened orchestrator still reads Not picked up', () => {
    const waiting = { ...orchestrator, status: 'waiting', not_picked_up: true }
    const status = mountRow(waiting, { interactive: true, monitoring: true }).find('[data-testid="jb-agent-status"]')
    expect(status.text()).toBe('Not picked up')
  })
})
