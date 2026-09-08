/**
 * ThreadPostBannerRow.spec.js — FE-9586
 *
 * The row that gives mention and directed-ask signals a banner, so their popouts
 * can be projections of it rather than events with a ten-minute deadline.
 *
 * The rules pinned here are the ones a reasonable implementation gets wrong:
 * one row for both classes rather than a stack, the directed ask outranking a
 * mention when both are live, a single-target CTA only when there IS one target,
 * and nothing rendered at all for zero.
 *
 * Edition Scope: Both
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import ThreadPostBannerRow from './ThreadPostBannerRow.vue'

const ROW = '[data-testid="thread-post-banner"]'
const TEXT = '[data-testid="thread-post-banner-text"]'
const CTA = '[data-testid="thread-post-cta"]'
const PILL = '[data-testid="thread-post-banner-pill"]'
const OVERFLOW = '[data-testid="thread-post-banner-pill-overflow"]'

function mention(n, chatId = `CHT-000${n}`) {
  return { thread_id: `t-${n}`, chat_id: chatId, message_ids: [`m-${n}`] }
}

function ask(n, chatId = `CHT-100${n}`) {
  return { thread_id: `a-${n}`, chat_id: chatId }
}

function row(props) {
  return mount(ThreadPostBannerRow, {
    props,
    global: { stubs: { 'v-icon': true } },
  })
}

describe('ThreadPostBannerRow (FE-9586)', () => {
  it('renders NOTHING when nothing is asking -- an empty strip is not a row', () => {
    const wrapper = row({ mentions: [], directedAsks: [] })

    expect(wrapper.find(ROW).exists()).toBe(false)
  })

  it('names the mention case in the singular', () => {
    const wrapper = row({ mentions: [mention(1)], directedAsks: [] })

    expect(wrapper.find(TEXT).text()).toBe('You were mentioned in a chat thread')
  })

  it('counts mentions when there are several', () => {
    const wrapper = row({ mentions: [mention(1), mention(2)], directedAsks: [] })

    expect(wrapper.find(TEXT).text()).toBe('You were mentioned in 2 chat threads')
  })

  it('says an ASK is waiting, which is a different sentence from being named', () => {
    const wrapper = row({ mentions: [], directedAsks: [ask(1)] })

    expect(wrapper.find(TEXT).text()).toBe('An agent is waiting on your answer')
  })

  it('falls back to a thread COUNT when both classes are live', () => {
    // "An agent asked you and also named you" is not a sentence for a 24px strip,
    // and picking one kind to report would hide the other.
    const wrapper = row({ mentions: [mention(1)], directedAsks: [ask(1)] })

    expect(wrapper.find(TEXT).text()).toBe('2 chat threads are waiting for you')
  })

  it('ONE row for both classes, never a stack', () => {
    const wrapper = row({ mentions: [mention(1), mention(2)], directedAsks: [ask(1)] })

    expect(wrapper.findAll(ROW)).toHaveLength(1)
  })

  it('emits the thread id when exactly one thing is asking', () => {
    const wrapper = row({ mentions: [mention(7)], directedAsks: [] })

    wrapper.find(CTA).trigger('click')

    expect(wrapper.emitted('open')[0]).toEqual(['t-7'])
  })

  it('emits NULL when several are asking -- the Hub list is the honest landing', () => {
    // Picking one would send the operator to an arbitrary thread and silently drop
    // the others from view.
    const wrapper = row({ mentions: [mention(1), mention(2)], directedAsks: [] })

    wrapper.find(CTA).trigger('click')

    expect(wrapper.emitted('open')[0]).toEqual([null])
  })

  it('labels the CTA for where it actually goes', () => {
    expect(row({ mentions: [mention(1)], directedAsks: [] }).find(CTA).text()).toBe('Open thread')
    expect(row({ mentions: [mention(1), mention(2)], directedAsks: [] }).find(CTA).text()).toBe(
      'Open Message Hub',
    )
  })

  it('puts the DIRECTED ask first: an explicit ask outranks being named in passing', () => {
    // Visible in the CTA target when one of each is live... which is the count case,
    // so assert it where it shows: the pill order.
    const wrapper = row({ mentions: [mention(1)], directedAsks: [ask(1)] })

    const pills = wrapper.findAll(PILL).map((p) => p.text())
    expect(pills[0]).toBe('CHT-1001')
  })

  it('caps the pills at four with a +N tail, so the row cannot grow', () => {
    const wrapper = row({
      mentions: [mention(1), mention(2), mention(3), mention(4), mention(5), mention(6)],
      directedAsks: [],
    })

    expect(wrapper.findAll(PILL)).toHaveLength(4)
    expect(wrapper.find(OVERFLOW).text()).toBe('+2')
  })

  it('de-duplicates the chat id, so two mentions in one thread show one pill', () => {
    const wrapper = row({
      mentions: [
        { thread_id: 't-1', chat_id: 'CHT-0001', message_ids: ['m-1'] },
        { thread_id: 't-1', chat_id: 'CHT-0001', message_ids: ['m-2'] },
      ],
      directedAsks: [],
    })

    expect(wrapper.findAll(PILL)).toHaveLength(1)
  })

  // FE-9589: the row used to carry no dismiss control at all, on the reasoning
  // that reading the thread was what cleared it. With several entries live its
  // CTA could not perform that read, so the row was permanent; the operator
  // ruled that anything on screen must be closeable where it stands.
  it('renders a dismiss X and emits `dismiss` when it is clicked', async () => {
    const wrapper = row({ mentions: [mention(1), mention(2)], directedAsks: [] })

    const x = wrapper.find('[data-testid="thread-post-banner-dismiss"]')
    expect(x.exists()).toBe(true)

    await x.trigger('click')

    expect(wrapper.emitted('dismiss')).toHaveLength(1)
    // The X is not the CTA: dismissing must not also open anything.
    expect(wrapper.emitted('open')).toBeUndefined()
  })

  it('never navigates on its own -- it only emits', () => {
    // The UI does not auto-navigate on agent activity: banners announce, the user
    // chooses to look. A component that routed itself would break that everywhere it
    // was mounted.
    const wrapper = row({ mentions: [mention(1)], directedAsks: [] })

    expect(wrapper.emitted('open')).toBeUndefined()
  })
})
