import { describe, it, expect } from 'vitest'
import {
  hubThreadRoute,
  isBatonFocus,
  focusMessageIdOf,
  resolveFocusMessageId,
  BATON_FOCUS,
} from './hubThreadRoute'

describe('hubThreadRoute (FE-9410)', () => {
  it('routes a thread object to its thread, carrying the baton context', () => {
    expect(hubThreadRoute({ thread_id: 'thr-42', subject: 'Anything' })).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: BATON_FOCUS },
    })
  })

  it('accepts a bare thread id, so a caller holding only an id need not fake a thread', () => {
    expect(hubThreadRoute('thr-42')).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: BATON_FOCUS },
    })
  })

  it('degrades to the plain Hub rather than emitting a deep link to nothing', () => {
    expect(hubThreadRoute(null)).toEqual({ path: '/hub' })
    expect(hubThreadRoute({})).toEqual({ path: '/hub' })
    expect(hubThreadRoute({ thread_id: '' })).toEqual({ path: '/hub' })
  })

  it('reads back its own flag, so the URL has one spelling on both sides', () => {
    expect(isBatonFocus(hubThreadRoute('thr-42').query)).toBe(true)
    expect(isBatonFocus({ thread: 'thr-42' })).toBe(false)
    expect(isBatonFocus(undefined)).toBe(false)
  })

  it('carries the message anchor when the thread names one (FE-9418)', () => {
    expect(
      hubThreadRoute({
        thread_id: 'thr-42',
        last_message: { id: 'msg-7', author: 'L25', excerpt: 'over to you' },
      }),
    ).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: BATON_FOCUS, message: 'msg-7' },
    })
  })

  it('omits the anchor entirely rather than emitting an empty one (FE-9418)', () => {
    const tailOnly = { path: '/hub', query: { thread: 'thr-42', focus: BATON_FOCUS } }
    expect(hubThreadRoute('thr-42')).toEqual(tailOnly)
    expect(hubThreadRoute({ thread_id: 'thr-42', last_message: null })).toEqual(tailOnly)
    expect(hubThreadRoute({ thread_id: 'thr-42', last_message: {} })).toEqual(tailOnly)
    for (const route of [hubThreadRoute('thr-42'), hubThreadRoute({ thread_id: 'thr-42' })]) {
      expect('message' in route.query).toBe(false)
    }
  })

  it('reads back its own anchor, so the URL has one spelling on both sides (FE-9418)', () => {
    const withAnchor = hubThreadRoute({ thread_id: 'thr-42', last_message: { id: 'msg-7' } })
    expect(focusMessageIdOf(withAnchor.query)).toBe('msg-7')
    expect(focusMessageIdOf(hubThreadRoute('thr-42').query)).toBe(null)
    expect(focusMessageIdOf(undefined)).toBe(null)
  })

  it('is the exact object both entry-point specs assert against', () => {
    expect(hubThreadRoute({ thread_id: 'thr-42' })).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'baton' },
    })
  })
})

describe('resolveFocusMessageId (FE-9418)', () => {
  const TAIL = 'msg-newest'
  const ANCHOR = 'msg-baton'
  const loaded = [{ message_id: 'msg-old' }, { message_id: ANCHOR }, { message_id: TAIL }]
  const batonQuery = (extra = {}) => ({ thread: 'thr-42', focus: BATON_FOCUS, ...extra })

  it('honours a named anchor over the newest post', () => {
    expect(resolveFocusMessageId(batonQuery({ message: ANCHOR }), 'thr-42', loaded)).toBe(ANCHOR)
  })

  it('falls back to the tail when no post is named — the bell rows travel this path', () => {
    expect(resolveFocusMessageId(batonQuery(), 'thr-42', loaded)).toBe(TAIL)
  })

  it('falls back to the tail when the named post is not loaded', () => {
    expect(resolveFocusMessageId(batonQuery({ message: 'msg-gone' }), 'thr-42', loaded)).toBe(TAIL)
  })

  it('marks nothing on an ordinary arrival, even when a post is named', () => {
    expect(resolveFocusMessageId({ thread: 'thr-42', message: ANCHOR }, 'thr-42', loaded)).toBe(null)
  })

  it('marks nothing once the operator has moved to a thread nobody handed them', () => {
    expect(resolveFocusMessageId(batonQuery({ message: ANCHOR }), 'thr-other', loaded)).toBe(null)
  })

  it('marks nothing when no thread is open or the timeline is empty', () => {
    expect(resolveFocusMessageId(batonQuery(), null, loaded)).toBe(null)
    expect(resolveFocusMessageId(batonQuery(), 'thr-42', [])).toBe(null)
    expect(resolveFocusMessageId(batonQuery(), 'thr-42', undefined)).toBe(null)
  })
})
