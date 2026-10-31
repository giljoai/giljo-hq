import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const T = 'thr-compact'

function post(id, over = {}) {
  return {
    thread_id: T,
    message_id: id,
    from_agent_id: 'implementer',
    from_kind: 'agent',
    from_display_name: 'implementer',
    content: `body of ${id}`,
    message_type: 'broadcast',
    created_at: '2026-10-05T11:59:00Z',
    ...over,
  }
}

describe('ThreadTimeline compact rows (FE-9742)', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    store.selectedThreadId = T
    store.participantsByThreadId = new Map([
      [T, [{ participant_id: 'implementer', participant_type: 'agent', display_name: 'implementer', role: 'implementer', harness: 'claude-code' }]],
    ])
  })

  const mountTl = (props = {}) => mount(ThreadTimeline, { props, global: { plugins: [pinia, vuetify] } })

  it('5: name, harness and date-time are siblings on one header line, bubble after it', async () => {
    await store.handleThreadMessage(post('m1'))
    const row = mountTl().get('[data-testid="timeline-message-m1"]')
    const header = row.get('.timeline-msg__header')
    expect(header.find('.timeline-msg__sender').text()).toBe('implementer')
    expect(header.find('[data-testid="message-harness"]').text()).toBe('Claude Code')
    expect(header.find('[data-testid="message-time"]').exists()).toBe(true)
    const html = row.html()
    expect(html.indexOf('timeline-msg__header')).toBeLessThan(html.indexOf('timeline-msg__content'))
  })

  it('5: action required is a pill on the name line, outline style, with its label', async () => {
    await store.handleThreadMessage(post('m1', { requires_action: true }))
    const pill = mountTl().get('.timeline-msg__header [data-testid="message-action-flag"]')
    expect(pill.text()).toContain('action required')
    expect(pill.classes()).toContain('timeline-msg__pill')
  })

  it('5: the waiting-on-you flag sits on the name line as a pill and the bubble is marked', async () => {
    await store.handleThreadMessage(post('m1'))
    await store.handleThreadMessage(post('m2', { created_at: '2026-10-05T12:30:00Z' }))
    const w = mountTl({ focusMessageId: 'm2' })
    const row = w.get('[data-testid="timeline-message-m2"]')
    const flag = row.get('.timeline-msg__header [data-testid="hub-focus-baton"]')
    expect(flag.text()).toBe('Waiting on you')
    expect(flag.classes()).toContain('timeline-msg__pill')
    expect(row.classes()).toContain('timeline-msg--focus')
  })

  it('5: a focused post that continues a run still gets a name line to carry its flag', async () => {
    await store.handleThreadMessage(post('m1'))
    await store.handleThreadMessage(post('m2', { created_at: '2026-10-05T12:00:00Z' }))
    const w = mountTl({ focusMessageId: 'm2' })
    expect(w.get('[data-testid="timeline-message-m2"] .timeline-msg__header [data-testid="hub-focus-baton"]').exists()).toBe(true)
  })

  it('5: an ordinary post carries no pills', async () => {
    await store.handleThreadMessage(post('m1'))
    const row = mountTl().get('[data-testid="timeline-message-m1"]')
    expect(row.find('.timeline-msg__pill').exists()).toBe(false)
  })
})
