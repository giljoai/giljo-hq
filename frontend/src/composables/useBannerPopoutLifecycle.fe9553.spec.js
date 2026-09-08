/**
 * useBannerPopoutLifecycle.fe9553.spec.js — FE-9553 ruling 4(c), completed by FE-9586.
 *
 * "Popouts follow banner state INCLUDING DEATH." A popout is a delivery medium
 * for a banner, so when the banner clears the popout must go with it --
 * otherwise an OS notification outlives the thing it was announcing, and the
 * operator answers a baton that was handed on ten minutes ago.
 *
 * The mechanism is a reconcile, not an event. Ruling 3 says the banner follows
 * STATE, not memory ("acting in the Hub clears the banner"), and there is no
 * "baton left you" event to listen for -- the baton simply stops pointing at you
 * in commHubStore.
 *
 * WHAT CHANGED IN FE-9586, and why four tests were deleted rather than kept:
 * this file used to pin a mention popout as NOT reconciled and an approval popout
 * as NOT reconciled, each closing on a ten-minute TTL instead. Both exceptions
 * existed because neither had banner state -- a mention raised no banner row at
 * all, and an APPROVAL_FOCUS popout is raised by a thread POST while the
 * raised-hand banner is a user_approvals record with no thread reference, so
 * matching them would have closed every approval popout on the first pass. Both
 * now have real state (useThreadPostAttention, off a server projection), so the
 * exceptions have no members, the TTL has nothing to guard, and tests asserting
 * "this one is NOT reconciled" would now pin the opposite of the intended
 * behaviour. They are replaced by their inverses below.
 *
 * The test this file gained that matters most is the last one: nothing is closed
 * while the state is merely UNLOADED. That is the near-miss this whole mechanism
 * keeps circling -- an empty list from an unhydrated source is indistinguishable
 * from a cleared banner, and reconciling on it closes every popout on mount,
 * silently, and only on a real OS.
 *
 * Edition Scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick, ref } from 'vue'

const mockYourTurnThreads = ref([])
vi.mock('./useYourTurnThreads', () => ({
  useYourTurnThreads: () => ({
    yourTurnThreads: mockYourTurnThreads,
    ensureThreadsLoaded: vi.fn(() => Promise.resolve()),
  }),
}))

const mockMentions = ref([])
const mockDirectedAsks = ref([])
const mockLoaded = ref(true)
vi.mock('./useThreadPostAttention', () => ({
  useThreadPostAttention: () => ({
    mentions: mockMentions,
    directedAsks: mockDirectedAsks,
    loaded: mockLoaded,
    ensureLoaded: vi.fn(() => Promise.resolve()),
    refresh: vi.fn(() => Promise.resolve()),
  }),
}))

import { popoutTag } from '@/utils/popoutTag'
import { clearPopoutRegistry, registerPopout, registeredPopoutTags } from '@/utils/popoutRegistry'
import { useBannerPopoutLifecycle } from './useBannerPopoutLifecycle'
import { BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'

/** A stand-in for a live OS Notification: all the lifecycle needs is close(). */
function fakePopout() {
  return { close: vi.fn() }
}

describe('FE-9553 ruling 4(c): a popout dies with its banner', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    clearPopoutRegistry()
    mockYourTurnThreads.value = []
    mockMentions.value = []
    mockDirectedAsks.value = []
    mockLoaded.value = true
  })

  it('closes a baton popout once the baton no longer points at the operator', async () => {
    const tag = popoutTag(BATON_FOCUS, 'thread-1')
    const popout = fakePopout()

    mockYourTurnThreads.value = [{ thread_id: 'thread-1', next_action_owner: 'user-001' }]
    useBannerPopoutLifecycle()
    registerPopout(tag, popout)
    await nextTick()

    // The banner is still up: the popout must survive.
    expect(popout.close).not.toHaveBeenCalled()

    // The operator acts in the Hub, the baton moves on, the banner clears.
    mockYourTurnThreads.value = []
    await nextTick()

    expect(popout.close).toHaveBeenCalledOnce()
    expect(registeredPopoutTags()).not.toContain(tag)
  })

  it('keeps a MENTION popout while the mention is unread, and closes it when it clears', async () => {
    // The inverse of the old "mentions are not reconciled" test. The mention now
    // has state: the server's unread-mention projection, thread-keyed, which is
    // the same key the tag carries.
    const tag = popoutTag(MENTION_FOCUS, 'thread-3')
    const popout = fakePopout()

    mockMentions.value = [{ thread_id: 'thread-3', message_ids: ['m1'] }]
    useBannerPopoutLifecycle()
    registerPopout(tag, popout)
    await nextTick()

    expect(popout.close).not.toHaveBeenCalled()

    // The operator reads the thread; the watermark passes the post; the projection
    // drops it; the banner clears.
    mockMentions.value = []
    await nextTick()

    expect(popout.close).toHaveBeenCalledOnce()
    expect(registeredPopoutTags()).not.toContain(tag)
  })

  it('keeps a DIRECTED action-request popout while it is unresolved, and closes it on acknowledgement', async () => {
    const tag = popoutTag(APPROVAL_FOCUS, 'thread-7')
    const popout = fakePopout()

    mockDirectedAsks.value = [{ thread_id: 'thread-7' }]
    useBannerPopoutLifecycle()
    registerPopout(tag, popout)
    await nextTick()

    expect(popout.close).not.toHaveBeenCalled()

    mockDirectedAsks.value = []
    await nextTick()

    expect(popout.close).toHaveBeenCalledOnce()
  })

  it('does not close a baton popout for a DIFFERENT thread that is still live', async () => {
    const goneTag = popoutTag(BATON_FOCUS, 'thread-gone')
    const liveTag = popoutTag(BATON_FOCUS, 'thread-live')
    const gone = fakePopout()
    const live = fakePopout()

    mockYourTurnThreads.value = [{ thread_id: 'thread-gone' }, { thread_id: 'thread-live' }]
    useBannerPopoutLifecycle()
    registerPopout(goneTag, gone)
    registerPopout(liveTag, live)
    await nextTick()

    mockYourTurnThreads.value = [{ thread_id: 'thread-live' }]
    await nextTick()

    expect(gone.close).toHaveBeenCalledOnce()
    expect(live.close).not.toHaveBeenCalled()
  })

  it('does not cross the reasons: a mention clearing leaves that thread\'s baton popout alone', async () => {
    // The tag carries the reason as well as the thread, so one thread can hold two
    // popouts for two different obligations. Reconciling by thread instead of by
    // tag would close both when either cleared.
    const batonTag = popoutTag(BATON_FOCUS, 'thread-9')
    const mentionTag = popoutTag(MENTION_FOCUS, 'thread-9')
    const baton = fakePopout()
    const mention = fakePopout()

    mockYourTurnThreads.value = [{ thread_id: 'thread-9' }]
    mockMentions.value = [{ thread_id: 'thread-9', message_ids: ['m1'] }]
    useBannerPopoutLifecycle()
    registerPopout(batonTag, baton)
    registerPopout(mentionTag, mention)
    await nextTick()

    mockMentions.value = []
    await nextTick()

    expect(mention.close).toHaveBeenCalledOnce()
    expect(baton.close).not.toHaveBeenCalled()
  })

  it('survives a popout whose close() throws -- one bad handle cannot strand the rest', async () => {
    // Notification handles are OS-backed and can throw or be already-dead.
    // A reconcile that gave up halfway would leave later popouts orphaned.
    const throwingTag = popoutTag(BATON_FOCUS, 'thread-throws')
    const okTag = popoutTag(BATON_FOCUS, 'thread-ok')
    const throwing = {
      close: vi.fn(() => {
        throw new Error('handle is dead')
      }),
    }
    const ok = fakePopout()

    mockYourTurnThreads.value = [{ thread_id: 'thread-throws' }, { thread_id: 'thread-ok' }]
    useBannerPopoutLifecycle()
    registerPopout(throwingTag, throwing)
    registerPopout(okTag, ok)
    await nextTick()

    mockYourTurnThreads.value = []
    await nextTick()

    expect(throwing.close).toHaveBeenCalled()
    expect(ok.close).toHaveBeenCalledOnce()
    expect(registeredPopoutTags()).toEqual([])
  })

  it('CLOSES NOTHING while the state is merely UNLOADED', async () => {
    // The near-miss, pinned. An empty projection from an unhydrated read is
    // indistinguishable from a cleared banner, and reconciling on it closes every
    // popout on mount -- silently, and only on a real OS where popouts exist.
    // This is why the projection starts at null and exposes `loaded`.
    const batonTag = popoutTag(BATON_FOCUS, 'thread-1')
    const mentionTag = popoutTag(MENTION_FOCUS, 'thread-2')
    const baton = fakePopout()
    const mention = fakePopout()

    mockLoaded.value = false
    mockYourTurnThreads.value = []
    mockMentions.value = []

    useBannerPopoutLifecycle()
    registerPopout(batonTag, baton)
    registerPopout(mentionTag, mention)
    await nextTick()

    expect(baton.close).not.toHaveBeenCalled()
    expect(mention.close).not.toHaveBeenCalled()
    expect(registeredPopoutTags()).toHaveLength(2)

    // And once the read lands and genuinely says nothing is waiting, they go.
    mockLoaded.value = true
    await nextTick()

    expect(baton.close).toHaveBeenCalledOnce()
    expect(mention.close).toHaveBeenCalledOnce()
  })
})
