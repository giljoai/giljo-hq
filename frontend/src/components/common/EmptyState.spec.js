/**
 * EmptyState.spec.js — FE-9538 (Ask 3)
 *
 * `compact` is an opt-in, additive prop: existing callers (LaunchTab.vue,
 * TasksTable.vue) omit it and must render byte-identically (48px icon,
 * uncompacted padding). A widget with a fixed, small container (like
 * ChainMissionWindow) opts in to shrink the icon and padding so the empty
 * state fits its box instead of clipping.
 *
 * Edition scope: Both
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import EmptyState from './EmptyState.vue'

const vuetify = createVuetify()

function mountEmptyState(props) {
  return mount(EmptyState, { props, global: { plugins: [vuetify] } })
}

describe('EmptyState', () => {
  it('defaults to the full-size icon and uncompacted class (existing callers unchanged)', () => {
    const wrapper = mountEmptyState({ icon: 'mdi-file-document-outline', title: 'Nothing yet' })
    expect(wrapper.find('.empty-state-icon').attributes('size')).toBe('48')
    expect(wrapper.find('.empty-state').classes()).not.toContain('empty-state--compact')
  })

  it('compact=true renders the smaller icon and the compact class', () => {
    const wrapper = mountEmptyState({
      icon: 'mdi-file-document-outline',
      title: 'Nothing yet',
      compact: true,
    })
    expect(wrapper.find('.empty-state-icon').attributes('size')).toBe('24')
    expect(wrapper.find('.empty-state').classes()).toContain('empty-state--compact')
  })
})
