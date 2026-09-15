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

describe('EmptyState — the action slot is additive', () => {
  const EXISTING_CALLER_SHAPES = [
    { icon: 'mdi-file-document-outline', title: 'No mission generated' },
    { icon: 'mdi-account-tie-outline', title: 'No conductor', compact: true },
    { icon: 'mdi-clipboard-text-outline', title: 'No tasks', description: 'Nothing here yet' },
  ]

  it.each(EXISTING_CALLER_SHAPES)('renders no action row without slot content (%o)', (props) => {
    const wrapper = mountEmptyState(props)
    expect(wrapper.find('.empty-state-actions').exists()).toBe(false)
  })

  it('a caller that fills the slot gets the action row', () => {
    const wrapper = mount(EmptyState, {
      props: { icon: 'mdi-account-multiple-outline', title: 'No agents' },
      slots: { default: '<button data-testid="do-it">Do it</button>' },
      global: { plugins: [vuetify] },
    })
    expect(wrapper.find('.empty-state-actions').exists()).toBe(true)
    expect(wrapper.find('[data-testid="do-it"]').exists()).toBe(true)
  })

  it('slot content sits AFTER the description, not inside it', () => {
    const wrapper = mount(EmptyState, {
      props: { icon: 'mdi-account-multiple-outline', title: 'No agents', description: 'Why' },
      slots: { default: '<button data-testid="do-it">Do it</button>' },
      global: { plugins: [vuetify] },
    })
    const children = [...wrapper.find('.empty-state').element.children].map((el) => el.className)
    expect(children).toEqual([
      expect.stringContaining('empty-state-icon'),
      'empty-state-title',
      'empty-state-description',
      'empty-state-actions',
    ])
  })
})
