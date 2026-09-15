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

    expect(popout.close).not.toHaveBeenCalled()

    mockYourTurnThreads.value = []
    await nextTick()

    expect(popout.close).toHaveBeenCalledOnce()
    expect(registeredPopoutTags()).not.toContain(tag)
  })

  it('keeps a MENTION popout while the mention is unread, and closes it when it clears', async () => {
    const tag = popoutTag(MENTION_FOCUS, 'thread-3')
    const popout = fakePopout()

    mockMentions.value = [{ thread_id: 'thread-3', message_ids: ['m1'] }]
    useBannerPopoutLifecycle()
    registerPopout(tag, popout)
    await nextTick()

    expect(popout.close).not.toHaveBeenCalled()

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

    mockLoaded.value = true
    await nextTick()

    expect(baton.close).toHaveBeenCalledOnce()
    expect(mention.close).toHaveBeenCalledOnce()
  })
})
