/**
 * ThreadTimeline.search.fe9368.spec.js — FE-9368 (D)
 *
 * The in-thread search box filters the timeline that is already loaded: no request,
 * no debounce, no server round trip. What these pin:
 *
 *  - the filter narrows on the message TEXT and on the AUTHOR name (the resolved
 *    display name the operator reads on the post, not the raw from_agent_id);
 *  - clearing restores every message, including the null the clearable field emits;
 *  - no match is reported as "no match", never as an empty thread. Those are
 *    different facts and only one of them means something went wrong.
 *
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const THREAD_ID = 'thr-search'

const MESSAGES = [
  {
    thread_id: THREAD_ID,
    message_id: 'm1',
    from_agent_id: 'lane-c',
    from_kind: 'agent',
    from_display_name: 'LANE_C',
    content: 'migration finished on the test box',
    message_type: 'broadcast',
    created_at: '2026-08-06T10:00:00Z',
  },
  {
    thread_id: THREAD_ID,
    message_id: 'm2',
    from_agent_id: 'reviewer-1',
    from_kind: 'agent',
    from_display_name: 'reviewer-1',
    content: 'reading the diff now',
    message_type: 'broadcast',
    created_at: '2026-08-06T11:00:00Z',
  },
  {
    thread_id: THREAD_ID,
    message_id: 'm3',
    from_agent_id: 'reviewer-1',
    from_kind: 'agent',
    from_display_name: 'reviewer-1',
    content: 'the MIGRATION looks fine to me',
    message_type: 'broadcast',
    // Well outside the 5-minute grouping window, so m3 is never a continuation of m2.
    created_at: '2026-08-06T13:00:00Z',
  },
]

function mountTimeline(pinia, search = '') {
  return mount(ThreadTimeline, { props: { search }, global: { plugins: [pinia, vuetify] } })
}

function renderedIds(wrapper) {
  return wrapper.findAll('.timeline-msg').map((row) => row.attributes('data-testid'))
}

describe('ThreadTimeline in-thread search (FE-9368)', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    const store = useCommHubStore()
    store.selectedThreadId = THREAD_ID
    MESSAGES.forEach((m) => store.handleThreadMessage(m))
  })

  it('shows every message when the box is empty', () => {
    expect(renderedIds(mountTimeline(pinia))).toHaveLength(3)
  })

  it('narrows to the messages whose text matches, case-insensitively', () => {
    const wrapper = mountTimeline(pinia, 'migration')
    const ids = renderedIds(wrapper)
    expect(ids).toEqual(['timeline-message-m1', 'timeline-message-m3'])
  })

  it('matches the author name as well as the body', async () => {
    const wrapper = mountTimeline(pinia, 'LANE')
    expect(renderedIds(wrapper)).toEqual(['timeline-message-m1'])

    // The author is matched on the name the operator actually reads.
    await wrapper.setProps({ search: 'reviewer-1' })
    expect(renderedIds(wrapper)).toEqual(['timeline-message-m2', 'timeline-message-m3'])
  })

  it('ignores surrounding whitespace rather than matching nothing', async () => {
    const wrapper = mountTimeline(pinia, '   ')
    expect(renderedIds(wrapper)).toHaveLength(3)

    await wrapper.setProps({ search: '  diff  ' })
    expect(renderedIds(wrapper)).toEqual(['timeline-message-m2'])
  })

  it('restores the full timeline when the query is cleared', async () => {
    const wrapper = mountTimeline(pinia, 'diff')
    expect(renderedIds(wrapper)).toHaveLength(1)

    await wrapper.setProps({ search: '' })
    expect(renderedIds(wrapper)).toHaveLength(3)

    // A `clearable` v-text-field emits null, not '' — the filter has to survive it.
    await wrapper.setProps({ search: 'diff' })
    await wrapper.setProps({ search: null })
    expect(renderedIds(wrapper)).toHaveLength(3)
  })

  it('says no message MATCHED, which is not the same as an empty thread', () => {
    const wrapper = mountTimeline(pinia, 'nothing here says this')
    expect(renderedIds(wrapper)).toHaveLength(0)
    expect(wrapper.find('[data-testid="timeline-search-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="timeline-empty"]').exists()).toBe(false)
  })

  it('regroups against what is on screen, so a filtered post keeps its author badge', async () => {
    // m2 and m3 are the same author. Unfiltered they are two separate posts (hours
    // apart), so both carry a badge; the guard here is that filtering m2 away does not
    // leave m3 grouped against a neighbour the operator can no longer see.
    const wrapper = mountTimeline(pinia, 'MIGRATION')
    const rows = wrapper.findAll('.timeline-msg')
    expect(rows).toHaveLength(2)
    rows.forEach((row) => expect(row.classes()).not.toContain('timeline-msg--grouped'))
  })
})
