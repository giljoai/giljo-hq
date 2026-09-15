import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'

const vuetify = createVuetify()
const THREAD_ID = 'thr-reasons'
const TARGET = 'msg-target'
const OTHER = 'msg-other'

function message(id, content) {
  return {
    thread_id: THREAD_ID,
    message_id: id,
    from_agent_id: 'L25',
    from_kind: 'agent',
    from_display_name: 'L25',
    content,
    message_type: 'broadcast',
    created_at: '2026-08-15T05:00:00Z',
  }
}

describe('ThreadTimeline focus reasons (FE-9436)', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    const store = useCommHubStore()
    store.selectedThreadId = THREAD_ID
    store.handleThreadMessage(message(OTHER, 'earlier chatter'))
    store.handleThreadMessage(message(TARGET, 'the post that wants you'))
    Element.prototype.scrollIntoView = vi.fn()
  })

  const mountTimeline = (props) =>
    mount(ThreadTimeline, { props, global: { plugins: [pinia, vuetify] } })

  const CASES = [
    { reason: BATON_FOCUS, testid: 'hub-focus-baton', copy: 'Waiting on you' },
    { reason: MENTION_FOCUS, testid: 'hub-focus-mention', copy: 'You were mentioned' },
    { reason: APPROVAL_FOCUS, testid: 'hub-focus-approval', copy: 'Needs your approval' },
  ]

  for (const { reason, testid, copy } of CASES) {
    it(`marks the focused post with ${reason} copy, and only that post`, () => {
      const wrapper = mountTimeline({ focusMessageId: TARGET, focusReason: reason })
      const focused = wrapper.find(`[data-testid="timeline-message-${TARGET}"]`)
      const other = wrapper.find(`[data-testid="timeline-message-${OTHER}"]`)

      expect(focused.classes()).toContain('timeline-msg--focus')
      expect(focused.find(`[data-testid="${testid}"]`).text()).toBe(copy)
      expect(other.exists()).toBe(true)
      expect(other.classes()).not.toContain('timeline-msg--focus')
      expect(other.find('.timeline-msg__focus-flag').exists()).toBe(false)
    })

    it(`uses the ONE flag mechanism for ${reason} — no second marker`, () => {
      const wrapper = mountTimeline({ focusMessageId: TARGET, focusReason: reason })
      expect(wrapper.findAll('.timeline-msg__focus-flag')).toHaveLength(1)
      expect(wrapper.findAll('.timeline-msg--focus')).toHaveLength(1)
      expect(wrapper.find(`[data-testid="${testid}"]`).classes()).toContain(
        'timeline-msg__focus-flag',
      )
    })
  }

  it('never renders the hand-off wording over a mention or an approval', () => {
    for (const reason of [MENTION_FOCUS, APPROVAL_FOCUS]) {
      const wrapper = mountTimeline({ focusMessageId: TARGET, focusReason: reason })
      expect(wrapper.find('.timeline-msg__focus-flag').text()).not.toContain('Waiting on you')
      expect(wrapper.find('[data-testid="hub-focus-baton"]').exists()).toBe(false)
    }
  })

  it('tints each reason differently, from tokens rather than per-reason markup', () => {
    const seen = CASES.map(({ reason }) => {
      const flag = mountTimeline({ focusMessageId: TARGET, focusReason: reason }).find(
        '.timeline-msg__focus-flag',
      )
      return flag.classes().find((c) => c.startsWith('timeline-msg__focus-flag--'))
    })
    expect(new Set(seen).size).toBe(CASES.length)
    expect(seen.every(Boolean)).toBe(true)
  })

  it('defaults to the hand-off when a caller names no reason (pre-FE-9436 behaviour)', () => {
    const wrapper = mountTimeline({ focusMessageId: TARGET })
    expect(wrapper.find('[data-testid="hub-focus-baton"]').text()).toBe('Waiting on you')
  })

  it('marks nothing when no post is focused, whatever the reason says', () => {
    const wrapper = mountTimeline({ focusMessageId: null, focusReason: MENTION_FOCUS })
    expect(wrapper.findAll('.timeline-msg__focus-flag')).toHaveLength(0)
    expect(wrapper.findAll('.timeline-msg--focus')).toHaveLength(0)
  })

  it('scrolls to the focused post on every reason, on the FE-9410 rule', async () => {
    for (const { reason } of CASES) {
      const wrapper = mountTimeline({ focusMessageId: null, focusReason: reason })
      await flushPromises()
      Element.prototype.scrollIntoView.mockClear()

      await wrapper.setProps({ focusMessageId: TARGET })
      await flushPromises()

      expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    }
  })
})
