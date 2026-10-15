import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import ChainMissionWindow from './ChainMissionWindow.vue'

const vuetify = createVuetify()

describe('ChainMissionWindow', () => {
  it('renders EmptyState with compact=true when there is no mission yet', () => {
    const wrapper = mount(ChainMissionWindow, {
      props: { mission: '' },
      global: { plugins: [vuetify] },
    })
    const emptyState = wrapper.findComponent({ name: 'EmptyState' })
    expect(emptyState.exists()).toBe(true)
    expect(emptyState.props('compact')).toBe(true)
  })

  it('renders the mission text (not the empty state) once one exists', () => {
    const wrapper = mount(ChainMissionWindow, {
      props: { mission: 'Ship the thing end to end.' },
      global: { plugins: [vuetify] },
    })
    expect(wrapper.findComponent({ name: 'EmptyState' }).exists()).toBe(false)
    expect(wrapper.text()).toContain('Ship the thing end to end.')
  })

  it('shows the Conductor Generated badge above the goal box, not inside it', () => {
    const wrapper = mount(ChainMissionWindow, {
      props: { mission: 'Ship the thing end to end.' },
      global: { plugins: [vuetify] },
    })
    const tag = wrapper.find('[data-testid="chain-mission-tag"]')
    const box = wrapper.find('[data-testid="chain-mission-window"]')
    expect(tag.text()).toMatch(/Conductor Generated$/)
    expect(box.find('[data-testid="chain-mission-tag"]').exists()).toBe(false)
    const row = wrapper.find('[data-testid="chain-mission-row"]')
    expect(row.exists()).toBe(true)
    expect(tag.element.parentElement).toBe(row.element)
    expect(row.element.nextElementSibling).toBe(box.element)
  })

  it('renders the actions slot on the badge row, after the badge', () => {
    const wrapper = mount(ChainMissionWindow, {
      props: { mission: 'Ship the thing end to end.' },
      slots: { actions: '<button class="slot-btn">Stop chain</button>' },
      global: { plugins: [vuetify] },
    })
    const row = wrapper.find('[data-testid="chain-mission-row"]')
    const tag = row.find('[data-testid="chain-mission-tag"]')
    const btn = row.find('.slot-btn')
    expect(tag.exists()).toBe(true)
    expect(btn.exists()).toBe(true)
    expect(tag.element.compareDocumentPosition(btn.element) & 4).toBe(4)
    expect(wrapper.find('[data-testid="chain-mission-window"] .slot-btn').exists()).toBe(false)
  })

  it('keeps the actions row even without a goal, and drops it when there is neither', () => {
    const withActions = mount(ChainMissionWindow, {
      props: { mission: '' },
      slots: { actions: '<button class="slot-btn">Stop chain</button>' },
      global: { plugins: [vuetify] },
    })
    expect(withActions.find('[data-testid="chain-mission-row"] .slot-btn').exists()).toBe(true)
    const bare = mount(ChainMissionWindow, { props: { mission: '' }, global: { plugins: [vuetify] } })
    expect(bare.find('[data-testid="chain-mission-row"]').exists()).toBe(false)
  })

  it('shows no badge while there is no goal yet', () => {
    const wrapper = mount(ChainMissionWindow, {
      props: { mission: '' },
      global: { plugins: [vuetify] },
    })
    expect(wrapper.find('[data-testid="chain-mission-tag"]').exists()).toBe(false)
  })
})
