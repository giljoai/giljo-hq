/**
 * ThreadTimeline.reasons.fe9436.spec.js — FE-9436
 *
 * FE-9410 gave the timeline ONE mark, and it said "Waiting on you" because the only
 * thing that could send an operator to a post was a baton. Now three things can, and the
 * operator ruling is that they share the surface and differ only in the reason.
 *
 * So the assertions that carry weight here are about what must NOT have been built:
 *
 *   - one flag element, one class, one scroll rule for all three reasons — a mention that
 *     grew its own marker would be the duplicate this work order exists to prevent;
 *   - a mention must never render the hand-off's words. "Waiting on you" over a post
 *     nobody handed over is the exact defect FE-9418 refused to ship, and it is what a
 *     naive unification reintroduces.
 *
 * FE-9410's own spec mounts this component with `focusMessageId` and NO reason, and it
 * still passes untouched — the default is the hand-off, so the pre-FE-9436 caller keeps
 * pre-FE-9436 behaviour.
 *
 * Edition scope: Both
 */
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
    // jsdom has no scrollIntoView; install rather than spy, or an absent method reads
    // as "the component chose not to scroll" (FE-9410's spec, same reason).
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
      // The other post is present and plausible, and must carry no mark at all.
      expect(other.exists()).toBe(true)
      expect(other.classes()).not.toContain('timeline-msg--focus')
      expect(other.find('.timeline-msg__focus-flag').exists()).toBe(false)
    })

    it(`uses the ONE flag mechanism for ${reason} — no second marker`, () => {
      const wrapper = mountTimeline({ focusMessageId: TARGET, focusReason: reason })
      // Exactly one flag in the whole timeline, and it is the FE-9410 element: same
      // class, same single instance. A reason that grew its own marker would show up
      // here as a second node, which is the duplication the ruling forbids.
      expect(wrapper.findAll('.timeline-msg__focus-flag')).toHaveLength(1)
      expect(wrapper.findAll('.timeline-msg--focus')).toHaveLength(1)
      expect(wrapper.find(`[data-testid="${testid}"]`).classes()).toContain(
        'timeline-msg__focus-flag',
      )
    })
  }

  it('never renders the hand-off wording over a mention or an approval', () => {
    // Stated as its own test because it is the failure the operator ruling is guarding
    // against, and because it stays true even if the copy above is later reworded.
    for (const reason of [MENTION_FOCUS, APPROVAL_FOCUS]) {
      const wrapper = mountTimeline({ focusMessageId: TARGET, focusReason: reason })
      expect(wrapper.find('.timeline-msg__focus-flag').text()).not.toContain('Waiting on you')
      expect(wrapper.find('[data-testid="hub-focus-baton"]').exists()).toBe(false)
    }
  })

  it('tints each reason differently, from tokens rather than per-reason markup', () => {
    // The chip is the ONLY difference between the three surfaces, so it has to actually
    // differ — and it has to do so by modifier class, not by a second element.
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
    // FE-9410's spec mounts exactly like this and must keep passing untouched.
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
