import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChainConductorCard from './ChainConductorCard.vue'

vi.mock('@/config/agentColors', () => ({
  getAgentColor: () => ({ hex: '#FFD700', rgb: '255, 215, 0' }),
}))

const conductor = {
  agent_display_name: 'orchestrator',
  project_id: null,
  job_metadata: { chain_conductor: true },
  status: 'running',
}

describe('ChainConductorCard', () => {
  it('renders the role label and conductor label', () => {
    const wrapper = mount(ChainConductorCard, {
      props: { conductor, label: 'Conductor (orchestrator A)' },
    })
    expect(wrapper.text()).toContain('Chain Conductor')
    expect(wrapper.text()).toContain('Conductor (orchestrator A)')
  })

  it('shows Running status when conductor is running', () => {
    const wrapper = mount(ChainConductorCard, {
      props: { conductor, label: 'Conductor' },
    })
    expect(wrapper.text()).toContain('Running')
  })

  it('shows Done status when conductor is completed', () => {
    const wrapper = mount(ChainConductorCard, {
      props: { conductor: { ...conductor, status: 'completed' }, label: 'Conductor' },
    })
    expect(wrapper.text()).toContain('Done')
  })

  it('has data-testid="chain-conductor-card"', () => {
    const wrapper = mount(ChainConductorCard, {
      props: { conductor, label: 'Conductor' },
    })
    expect(wrapper.find('[data-testid="chain-conductor-card"]').exists()).toBe(true)
  })
})
