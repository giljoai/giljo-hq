import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WelcomeTeamSection from './WelcomeTeamSection.vue'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'router-link': { template: '<a><slot /></a>' },
}

describe('WelcomeTeamSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const sampleTemplates = [
    { id: 'tmpl-1', name: 'implementer', description: 'Writes code', badge: 'IM', color: '#6db3e4' },
    { id: 'tmpl-2', name: 'tester', description: 'Tests code', badge: 'TS', color: '#a87cce' },
  ]

  function mountTeam(props = {}) {
    return mount(WelcomeTeamSection, {
      props: {
        activeTemplates: sampleTemplates,
        emptySlots: 2,
        totalSlots: 16,
        ...props,
      },
      global: { stubs: globalStubs },
    })
  }

  it('renders the orchestrator card', () => {
    const wrapper = mountTeam()
    expect(wrapper.text()).toContain('orchestrator')
  })

  it('renders one card per active template', () => {
    const wrapper = mountTeam()
    const cards = wrapper.findAll('.team-card:not(.empty-slot)')
    expect(cards).toHaveLength(3)
  })

  it('renders empty slots', () => {
    const wrapper = mountTeam({ emptySlots: 3 })
    expect(wrapper.findAll('.team-card.empty-slot')).toHaveLength(3)
  })

  it('shows slot count as "activeTemplates+1 / totalSlots slots"', () => {
    const wrapper = mountTeam()
    expect(wrapper.find('.team-slots').text()).toContain('3')
    expect(wrapper.find('.team-slots').text()).toContain('16')
  })
})


describe('WelcomeTeamSection — no product yet', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function mountTeam(props = {}) {
    return mount(WelcomeTeamSection, {
      props: { activeTemplates: [], emptySlots: 0, totalSlots: 16, ...props },
      global: { stubs: globalStubs },
    })
  }

  it('points at creating a product rather than reporting missing agents', () => {
    const wrapper = mountTeam({ hasProduct: false })
    const panel = wrapper.find('[data-testid="team-no-product"]')

    expect(panel.exists()).toBe(true)
    expect(panel.text()).toMatch(/create a product/i)
    expect(panel.text()).toMatch(/crew of agents/i)
    expect(panel.text()).not.toMatch(/no agents|none found|empty/i)
  })

  it('shows no empty slots and no slot count when there is no product', () => {
    const wrapper = mountTeam({ hasProduct: false, emptySlots: 5 })

    expect(wrapper.findAll('.empty-slot')).toHaveLength(0)
    expect(wrapper.find('.team-slots').exists()).toBe(false)
  })

  it('renders the normal grid once a product exists', () => {
    const wrapper = mountTeam({ hasProduct: true, emptySlots: 2 })

    expect(wrapper.find('[data-testid="team-no-product"]').exists()).toBe(false)
    expect(wrapper.find('.team-slots').exists()).toBe(true)
  })
})
