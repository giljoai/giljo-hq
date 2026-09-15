import { describe, it, expect } from 'vitest'
import {
  hubThreadRoute,
  isBatonFocus,
  isActionFocus,
  focusReasonOf,
  focusMessageIdOf,
  resolveFocusMessageId,
  BATON_FOCUS,
  MENTION_FOCUS,
  APPROVAL_FOCUS,
} from './hubThreadRoute'

describe('hubThreadRoute reasons (FE-9436)', () => {
  it('defaults to the hand-off, so every pre-FE-9436 caller keeps its exact route', () => {
    expect(hubThreadRoute('thr-42')).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'baton' },
    })
    expect(hubThreadRoute({ thread_id: 'thr-42', last_message: { id: 'msg-7' } })).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'baton', message: 'msg-7' },
    })
  })

  it('stamps the reason it was given', () => {
    expect(hubThreadRoute('thr-42', { reason: MENTION_FOCUS }).query.focus).toBe('mention')
    expect(hubThreadRoute('thr-42', { reason: APPROVAL_FOCUS }).query.focus).toBe('approval')
  })

  it('carries an anchor the CALLER names, which is how a mention pins at all', () => {
    expect(hubThreadRoute('thr-42', { reason: MENTION_FOCUS, messageId: 'msg-99' })).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'mention', message: 'msg-99' },
    })
  })

  it('prefers the caller-named anchor over the thread summary, which can be stale', () => {
    const route = hubThreadRoute(
      { thread_id: 'thr-42', last_message: { id: 'msg-stale' } },
      { reason: MENTION_FOCUS, messageId: 'msg-live' },
    )
    expect(route.query.message).toBe('msg-live')
  })

  it('omits the anchor rather than emitting an empty one, on every reason', () => {
    for (const reason of [BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS]) {
      const route = hubThreadRoute('thr-42', { reason })
      expect('message' in route.query).toBe(false)
      expect(hubThreadRoute('thr-42', { reason, messageId: null }).query).toEqual(route.query)
      expect(hubThreadRoute('thr-42', { reason, messageId: '' }).query).toEqual(route.query)
    }
  })

  it('degrades to the plain Hub with no id, whatever the reason', () => {
    expect(hubThreadRoute(null, { reason: MENTION_FOCUS })).toEqual({ path: '/hub' })
    expect(hubThreadRoute({}, { reason: APPROVAL_FOCUS, messageId: 'msg-9' })).toEqual({
      path: '/hub',
    })
  })

  it('emits NO focus at all for a reason it does not recognise', () => {
    const route = hubThreadRoute('thr-42', { reason: 'urgent-ish', messageId: 'msg-9' })
    expect(route).toEqual({ path: '/hub', query: { thread: 'thr-42' } })
    expect(resolveFocusMessageId(route.query, 'thr-42', [{ message_id: 'msg-9' }])).toBe(null)
  })
})

describe('focus predicates stay honest about which reason they mean (FE-9436)', () => {
  it('isBatonFocus stays NARROW — false for a mention, false for an approval', () => {
    expect(isBatonFocus({ focus: BATON_FOCUS })).toBe(true)
    expect(isBatonFocus({ focus: MENTION_FOCUS })).toBe(false)
    expect(isBatonFocus({ focus: APPROVAL_FOCUS })).toBe(false)
  })

  it('isActionFocus covers all three and nothing else', () => {
    expect(isActionFocus({ focus: BATON_FOCUS })).toBe(true)
    expect(isActionFocus({ focus: MENTION_FOCUS })).toBe(true)
    expect(isActionFocus({ focus: APPROVAL_FOCUS })).toBe(true)
    expect(isActionFocus({ focus: 'urgent-ish' })).toBe(false)
    expect(isActionFocus({ thread: 'thr-42' })).toBe(false)
    expect(isActionFocus(undefined)).toBe(false)
  })

  it('focusReasonOf reads back exactly what was written, or null', () => {
    expect(focusReasonOf(hubThreadRoute('t').query)).toBe(BATON_FOCUS)
    expect(focusReasonOf(hubThreadRoute('t', { reason: MENTION_FOCUS }).query)).toBe(MENTION_FOCUS)
    expect(focusReasonOf(hubThreadRoute('t', { reason: APPROVAL_FOCUS }).query)).toBe(APPROVAL_FOCUS)
    expect(focusReasonOf({ focus: 'urgent-ish' })).toBe(null)
    expect(focusReasonOf(undefined)).toBe(null)
  })

  it('the anchor reader is indifferent to the reason, as it always was', () => {
    expect(focusMessageIdOf({ focus: MENTION_FOCUS, message: 'msg-9' })).toBe('msg-9')
    expect(focusMessageIdOf({ focus: APPROVAL_FOCUS })).toBe(null)
  })
})

describe('resolveFocusMessageId across all three reasons (FE-9436)', () => {
  const TAIL = 'msg-newest'
  const ANCHOR = 'msg-anchor'
  const loaded = [{ message_id: 'msg-old' }, { message_id: ANCHOR }, { message_id: TAIL }]
  const q = (reason, extra = {}) => ({ thread: 'thr-42', focus: reason, ...extra })

  for (const reason of [BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS]) {
    it(`honours a named anchor over the newest post — ${reason}`, () => {
      expect(resolveFocusMessageId(q(reason, { message: ANCHOR }), 'thr-42', loaded)).toBe(ANCHOR)
    })

    it(`falls back to the tail when no post is named — ${reason}`, () => {
      expect(resolveFocusMessageId(q(reason), 'thr-42', loaded)).toBe(TAIL)
    })

    it(`falls back to the tail when the named post is not loaded — ${reason}`, () => {
      expect(resolveFocusMessageId(q(reason, { message: 'gone' }), 'thr-42', loaded)).toBe(TAIL)
    })

    it(`marks nothing once the operator moved to another thread — ${reason}`, () => {
      expect(resolveFocusMessageId(q(reason, { message: ANCHOR }), 'thr-other', loaded)).toBe(null)
    })

    it(`marks nothing with no thread open or an empty timeline — ${reason}`, () => {
      expect(resolveFocusMessageId(q(reason), null, loaded)).toBe(null)
      expect(resolveFocusMessageId(q(reason), 'thr-42', [])).toBe(null)
      expect(resolveFocusMessageId(q(reason), 'thr-42', undefined)).toBe(null)
    })
  }

  it('marks nothing on an ordinary deep link that merely names a post', () => {
    expect(resolveFocusMessageId({ thread: 'thr-42', message: ANCHOR }, 'thr-42', loaded)).toBe(null)
  })

  it('marks nothing on a hand-crafted URL carrying an unrecognised reason', () => {
    expect(resolveFocusMessageId(q('urgent-ish', { message: ANCHOR }), 'thr-42', loaded)).toBe(null)
  })
})
