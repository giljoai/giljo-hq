/**
 * ThreadTimeline.baton.fe9410.spec.js — FE-9410
 *
 * The last step of "navigate to the message": once the Hub has resolved WHICH post a
 * baton notification pointed at, the timeline has to actually take the operator there
 * and say so. HubView's spec pins that the id is resolved and handed over; this pins
 * what the timeline does with it.
 *
 * The scroll assertions matter because the timeline already had a scroll rule — jump to
 * the bottom whenever messages arrive. Two scrolls competing in one frame is how a view
 * lands somewhere neither rule intended, so the focused post has to WIN, and the plain
 * arrival has to keep the old behaviour untouched.
 *
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const THREAD_ID = 'thr-baton'

function message(id, content) {
  return {
    thread_id: THREAD_ID,
    message_id: id,
    from_agent_id: 'L25',
    from_kind: 'agent',
    from_display_name: 'L25',
    content,
    message_type: 'broadcast',
    created_at: '2026-08-13T05:00:00Z',
  }
}

describe('ThreadTimeline baton focus (FE-9410)', () => {
  let pinia
  let scrollIntoView

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    const store = useCommHubStore()
    store.selectedThreadId = THREAD_ID
    store.handleThreadMessage(message('msg-old', 'earlier chatter'))
    store.handleThreadMessage(message('msg-baton', 'over to you'))

    // jsdom does not implement scrollIntoView, so it has to be installed rather than
    // spied on — an absent method would otherwise read as "the component chose not to
    // scroll" when it in fact could not.
    scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
  })

  function mountTimeline(focusMessageId = null) {
    return mount(ThreadTimeline, {
      props: { focusMessageId },
      global: { plugins: [pinia, vuetify] },
    })
  }

  it('marks the focused post, and only that post', () => {
    const wrapper = mountTimeline('msg-baton')
    const focused = wrapper.find('[data-testid="timeline-message-msg-baton"]')
    const other = wrapper.find('[data-testid="timeline-message-msg-old"]')

    expect(focused.classes()).toContain('timeline-msg--focus')
    expect(focused.find('[data-testid="hub-focus-baton"]').exists()).toBe(true)
    expect(other.classes()).not.toContain('timeline-msg--focus')
    expect(other.find('[data-testid="hub-focus-baton"]').exists()).toBe(false)
  })

  it('marks nothing when the operator did not arrive from a notification', () => {
    const wrapper = mountTimeline(null)
    expect(wrapper.find('[data-testid="hub-focus-baton"]').exists()).toBe(false)
    expect(wrapper.findAll('.timeline-msg--focus').length).toBe(0)
  })

  it('scrolls the focused post into view when the focus lands after the messages', async () => {
    // The operator clicks the banner while already inside the Hub: the thread is
    // loaded, the message count never changes, and only the target is new.
    const wrapper = mountTimeline(null)
    await flushPromises()
    scrollIntoView.mockClear()

    await wrapper.setProps({ focusMessageId: 'msg-baton' })
    await flushPromises()

    expect(scrollIntoView).toHaveBeenCalled()
  })

  it('leaves an unfocused timeline on its own bottom-scroll rule', async () => {
    const wrapper = mountTimeline(null)
    await flushPromises()
    scrollIntoView.mockClear()

    const store = useCommHubStore()
    store.handleThreadMessage(message('msg-new', 'a later post'))
    await flushPromises()

    expect(scrollIntoView).not.toHaveBeenCalled()
    expect(wrapper.findAll('.timeline-msg').length).toBe(3)
  })
})
