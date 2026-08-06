/**
 * ProjectTabStrip.spec.js — FE-9239
 * Badge-state derivation (review > completed > working > planning > waiting) and
 * pulse behavior for the chain tab strip. Presentational — no store mocks needed.
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProjectTabStrip from './ProjectTabStrip.vue'

function makeTab(overrides = {}) {
  return {
    projectId: 'p1',
    order: 0,
    name: 'Project One',
    taxonomyAlias: '',
    taxonomy: null,
    productId: 'prod-1',
    status: 'pending',
    isCurrent: false,
    isCompleted: false,
    needsReview: false,
    isStarted: false,
    isWorking: false,
    isPlanning: false,
    ...overrides,
  }
}

function badgeEl(wrapper) {
  return wrapper.find('.chain-tab__badge')
}

describe('ProjectTabStrip — badge states', () => {
  it('renders WAITING when no other state flag is set', () => {
    const wrapper = mount(ProjectTabStrip, { props: { tabs: [makeTab()] } })
    const badge = badgeEl(wrapper)
    expect(badge.text()).toBe('WAITING')
    expect(badge.classes()).toContain('chain-tab__badge--waiting')
    expect(badge.classes()).not.toContain('chain-tab__badge--pulse')
  })

  it('renders PLANNING when isPlanning is true (FE-9239)', () => {
    const wrapper = mount(ProjectTabStrip, {
      props: { tabs: [makeTab({ isPlanning: true })] },
    })
    const badge = badgeEl(wrapper)
    expect(badge.text()).toBe('PLANNING')
    expect(badge.classes()).toContain('chain-tab__badge--planning')
  })

  it('PLANNING does not pulse (not an attention state)', () => {
    const wrapper = mount(ProjectTabStrip, {
      props: { tabs: [makeTab({ isPlanning: true })] },
    })
    expect(badgeEl(wrapper).classes()).not.toContain('chain-tab__badge--pulse')
  })

  it('WORKING still pulses (regression guard on the existing pulse contract)', () => {
    const wrapper = mount(ProjectTabStrip, {
      props: { tabs: [makeTab({ isWorking: true, isPlanning: true })] },
    })
    const badge = badgeEl(wrapper)
    expect(badge.text()).toBe('WORKING')
    expect(badge.classes()).toContain('chain-tab__badge--pulse')
  })

  it('REVIEW still pulses and outranks every other flag', () => {
    const wrapper = mount(ProjectTabStrip, {
      props: {
        tabs: [makeTab({ needsReview: true, isCompleted: true, isWorking: true, isPlanning: true })],
      },
    })
    const badge = badgeEl(wrapper)
    expect(badge.text()).toBe('REVIEW')
    expect(badge.classes()).toContain('chain-tab__badge--pulse')
  })

  it('COMPLETED outranks WORKING and PLANNING', () => {
    const wrapper = mount(ProjectTabStrip, {
      props: { tabs: [makeTab({ isCompleted: true, isWorking: true, isPlanning: true })] },
    })
    expect(badgeEl(wrapper).text()).toBe('COMPLETED')
  })

  it('WORKING outranks PLANNING', () => {
    const wrapper = mount(ProjectTabStrip, {
      props: { tabs: [makeTab({ isWorking: true, isPlanning: true })] },
    })
    expect(badgeEl(wrapper).text()).toBe('WORKING')
  })

  it('PLANNING outranks WAITING (the default)', () => {
    const wrapper = mount(ProjectTabStrip, {
      props: { tabs: [makeTab({ isPlanning: true })] },
    })
    expect(badgeEl(wrapper).text()).toBe('PLANNING')
  })
})
