import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

import StatusBadge from './StatusBadge.vue'
import { useProjectStatusesStore } from '@/stores/projectStatusesStore'

describe('StatusBadge — parked status (IMP-9258)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders "Parked" (not "Unknown") when the store carries the parked metadata entry', () => {
    const store = useProjectStatusesStore()
    store.statuses = [
      { value: 'inactive', label: 'Inactive', color_token: 'color-text-muted' },
      { value: 'active', label: 'Active', color_token: 'color-agent-implementer' },
      { value: 'cancelled', label: 'Cancelled', color_token: 'color-status-blocked' },
      { value: 'parked', label: 'Parked', color_token: 'color-agent-reviewer' },
    ]
    store.loaded = true

    const wrapper = mount(StatusBadge, { props: { status: 'parked' } })

    expect(wrapper.text()).toBe('Parked')
    expect(wrapper.text()).not.toContain('Unknown')
  })

  it('falls back to a capitalized label (not "Unknown") if the store has not loaded the parked entry yet', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'parked' } })

    expect(wrapper.text()).toBe('Parked')
  })

  it('still renders "Unknown" only for a truly unrecognized status value', () => {
    const wrapper = mount(StatusBadge, { props: { status: '' } })

    expect(wrapper.text()).toBe('Unknown')
  })
})
