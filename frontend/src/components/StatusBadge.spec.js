/**
 * StatusBadge.spec.js — IMP-9258 regression at the failing layer.
 *
 * Guards the exact failure mode called out in memory
 * `feedback_store_status_writes_check_display_map`: a status value with no
 * entry in the metadata map renders "Unknown" and masks the real state. The
 * project-status label/color map is backend-driven (single source of truth,
 * BE-5039) via `GET /api/v1/project-statuses/` -> `projectStatusesStore`, so
 * this test seeds the store the same way a real fetch would and asserts the
 * `parked` status resolves to the real "Parked" label -- not the fallback.
 *
 * Edition scope: CE (shared frontend; SaaS reuses the same store/component).
 */
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
    // Shape mirrors the real GET /api/v1/project-statuses/ payload.
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
    // Defensive: before the store fetches (or against a stale cache), the
    // component must not render the literal string "Unknown" for a real,
    // known-by-the-backend status -- it capitalizes the raw value instead.
    const wrapper = mount(StatusBadge, { props: { status: 'parked' } })

    expect(wrapper.text()).toBe('Parked')
  })

  it('still renders "Unknown" only for a truly unrecognized status value', () => {
    const wrapper = mount(StatusBadge, { props: { status: '' } })

    expect(wrapper.text()).toBe('Unknown')
  })
})
