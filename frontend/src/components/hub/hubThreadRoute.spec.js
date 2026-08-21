/**
 * hubThreadRoute.spec.js — FE-9410
 *
 * The shared route both baton notifications navigate through.
 *
 * The last test here is the drift guard the whole helper exists for: the two entry-point
 * specs assert their pushes against a hand-written literal, and this pins that the
 * helper produces exactly that literal. If someone changes the route shape in one place,
 * the other spec goes red rather than the two surfaces quietly disagreeing — which is
 * the failure FE-9410 was reported as in the first place.
 *
 * Edition scope: Both
 */
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
    // The thread-list payload's last_message now names the post it summarises, so the
    // hand-off can point at the POST rather than at "whatever is newest when you get
    // there" — a different row the moment anything else lands in between.
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
    // Three real callers cannot supply one: a bare id (the bell rows), a thread nobody
    // has posted in, and a payload from a server that predates the anchor. Each must
    // produce the PRE-FE-9418 route byte for byte, because that route still works — the
    // Hub falls back to the thread tail exactly as it did before.
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
    // Change this shape and SystemStatusBanner.baton.fe9410.spec.js +
    // HubView.baton.fe9410.spec.js both go red on the same line. That is deliberate:
    // one hand-off must not be able to land in two different places.
    expect(hubThreadRoute({ thread_id: 'thr-42' })).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'baton' },
    })
  })
})

describe('resolveFocusMessageId (FE-9418)', () => {
  const TAIL = 'msg-newest'
  const ANCHOR = 'msg-baton'
  // Deliberately NOT last: a fixture whose anchor is already the tail cannot tell the
  // named-anchor rule from the fallback, so every case below would pass on either.
  const loaded = [{ message_id: 'msg-old' }, { message_id: ANCHOR }, { message_id: TAIL }]
  const batonQuery = (extra = {}) => ({ thread: 'thr-42', focus: BATON_FOCUS, ...extra })

  it('honours a named anchor over the newest post', () => {
    expect(resolveFocusMessageId(batonQuery({ message: ANCHOR }), 'thr-42', loaded)).toBe(ANCHOR)
  })

  it('falls back to the tail when no post is named — the bell rows travel this path', () => {
    expect(resolveFocusMessageId(batonQuery(), 'thr-42', loaded)).toBe(TAIL)
  })

  it('falls back to the tail when the named post is not loaded', () => {
    // An anchor nothing matches would mark no post and scroll nowhere, which is worse
    // than the approximation it replaced. Unresolvable is treated as unnamed.
    expect(resolveFocusMessageId(batonQuery({ message: 'msg-gone' }), 'thr-42', loaded)).toBe(TAIL)
  })

  it('marks nothing on an ordinary arrival, even when a post is named', () => {
    // The flag decides WHETHER to mark; the anchor only decides WHICH. A plain ?thread=
    // deep link is not a hand-off and must never acquire a "Waiting on you" label.
    expect(resolveFocusMessageId({ thread: 'thr-42', message: ANCHOR }, 'thr-42', loaded)).toBe(null)
  })

  it('marks nothing once the operator has moved to a thread nobody handed them', () => {
    // FE-9410's 441dec7b0 guard: focus=baton outlives the arrival and stays in the URL.
    expect(resolveFocusMessageId(batonQuery({ message: ANCHOR }), 'thr-other', loaded)).toBe(null)
  })

  it('marks nothing when no thread is open or the timeline is empty', () => {
    expect(resolveFocusMessageId(batonQuery(), null, loaded)).toBe(null)
    expect(resolveFocusMessageId(batonQuery(), 'thr-42', [])).toBe(null)
    expect(resolveFocusMessageId(batonQuery(), 'thr-42', undefined)).toBe(null)
  })
})
