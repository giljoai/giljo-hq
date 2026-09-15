import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }) }))

import ThreadCard from '@/components/hub/ThreadCard.vue'
import HubThreadHeader from '@/components/hub/HubThreadHeader.vue'
import { formatHubDateTime, threadDates, CREATED_LABEL, LAST_MESSAGE_LABEL } from '@/components/hub/hubDateTime'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()

const THREAD = {
  thread_id: 't-dates',
  chat_id: 'CHT-0042',
  subject: 'Dates on the card',
  status: 'open',
  project_id: null,
  participants: [],
  created_at: '2026-08-01T09:05:00Z',
  last_activity_at: '2026-09-08T16:40:00Z',
  last_message: { id: 'm9', author: 'LANE_C', excerpt: 'done', created_at: '2026-09-08T16:40:00Z' },
}

describe('formatHubDateTime / threadDates', () => {
  it('renders a local date AND time, never a relative token', () => {
    const out = formatHubDateTime(THREAD.created_at)
    expect(out).toMatch(/2026/)
    expect(out).toMatch(/\d{1,2}:\d{2}/)
    expect(out).not.toMatch(/^\d+[mhd]$/)
  })

  it('returns an empty string for a missing or unparsable value', () => {
    expect(formatHubDateTime(null)).toBe('')
    expect(formatHubDateTime('not a date')).toBe('')
  })

  it('takes the last message from the post itself, falling back to last_activity_at', () => {
    const withPost = threadDates(THREAD)
    expect(withPost.created).toBe(formatHubDateTime(THREAD.created_at))
    expect(withPost.lastMessage).toBe(formatHubDateTime(THREAD.last_message.created_at))

    const noPost = threadDates({ ...THREAD, last_message: null })
    expect(noPost.lastMessage).toBe(formatHubDateTime(THREAD.last_activity_at))

    const nothing = threadDates({ ...THREAD, last_message: null, last_activity_at: null })
    expect(nothing.lastMessage).toBe('')
  })
})

describe('ThreadCard dates (FE-9593)', () => {
  function mountCard(thread) {
    return mount(ThreadCard, { props: { thread }, global: { plugins: [vuetify] } })
  }

  it('shows created and last-message date-times, each labelled', () => {
    const w = mountCard(THREAD)
    const created = w.find('[data-testid="thread-dates-created"]')
    const last = w.find('[data-testid="thread-dates-last-message"]')
    expect(created.text()).toContain(CREATED_LABEL)
    expect(created.text()).toContain(formatHubDateTime(THREAD.created_at))
    expect(last.text()).toContain(LAST_MESSAGE_LABEL)
    expect(last.text()).toContain(formatHubDateTime(THREAD.last_message.created_at))
    expect(created.find('time').attributes('datetime')).toBe(THREAD.created_at)
  })

  it('no longer renders the relative "1d" token', () => {
    const w = mountCard(THREAD)
    expect(w.find('[data-testid="thread-card-time"]').exists()).toBe(false)
    expect(w.text()).not.toMatch(/\b\d+d\b/)
  })

  it('shows the created date alone when the thread has no message yet', () => {
    const w = mountCard({ ...THREAD, last_message: null, last_activity_at: null })
    expect(w.find('[data-testid="thread-dates-created"]').exists()).toBe(true)
    expect(w.find('[data-testid="thread-dates-last-message"]').exists()).toBe(false)
  })
})

describe('HubThreadHeader dates (FE-9593)', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    const store = useCommHubStore()
    store._testSeedThread(THREAD)
    store.selectedThreadId = THREAD.thread_id
  })

  it('carries the SAME two labelled values as the card, under the serial', () => {
    const w = mount(HubThreadHeader, {
      global: { plugins: [pinia, vuetify], stubs: { AgentPill: true, ThreadRetagMenu: true } },
    })
    const dates = w.find('[data-testid="thread-header-dates"]')
    expect(dates.exists()).toBe(true)
    const created = dates.find('[data-testid="thread-dates-created"]')
    const last = dates.find('[data-testid="thread-dates-last-message"]')
    expect(created.text()).toContain(CREATED_LABEL)
    expect(created.find('time').text()).toBe(formatHubDateTime(THREAD.created_at))
    expect(last.text()).toContain(LAST_MESSAGE_LABEL)
    expect(last.find('time').text()).toBe(formatHubDateTime(THREAD.last_message.created_at))
    const html = w.html()
    expect(html.indexOf('thread-header-serial')).toBeLessThan(html.indexOf('thread-header-dates'))
  })
})
