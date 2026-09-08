/**
 * ChainMissionWindow.spec.js — FE-9538 (Ask 3)
 *
 * Pins the fix for the clipped conductor placeholder: this window caps its
 * body at max-height:180px (see the component's own style block), so its
 * empty state must render EmptyState with `compact` -- otherwise EmptyState's
 * default full-page padding+icon budget (~190px) overflows the box.
 *
 * Edition scope: Both
 */
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
})
