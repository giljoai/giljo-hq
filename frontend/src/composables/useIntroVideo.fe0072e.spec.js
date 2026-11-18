import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ patch: vi.fn() }))
vi.mock('@/services/api', () => {
  const apiObj = { auth: { updateSetupState: h.patch } }
  return { default: apiObj, api: apiObj }
})

import {
  INTRO_VIDEO_RELEASED_AT,
  INTRO_VIDEO_STALL_MS,
  isFirstThirtyDays,
  isPreReleaseAccount,
  useIntroVideo,
} from './useIntroVideo'
import { useUserStore } from '@/stores/user'

const DAY = 24 * 60 * 60 * 1000
const NOW = Date.parse('2026-12-20T12:00:00Z')
const ago = (days) => new Date(NOW - days * DAY).toISOString()

describe('the 30-day rule', () => {
  it('is true at 29 days and false at 31', () => {
    expect(isFirstThirtyDays(ago(29), NOW)).toBe(true)
    expect(isFirstThirtyDays(ago(31), NOW)).toBe(false)
  })
  it('is false for a missing or unreadable created_at', () => {
    expect(isFirstThirtyDays(undefined, NOW)).toBe(false)
    expect(isFirstThirtyDays(null, NOW)).toBe(false)
    expect(isFirstThirtyDays('not a date', NOW)).toBe(false)
  })
})

describe('the banner row audience', () => {
  it('is true before the release date and false after it', () => {
    const released = Date.parse(INTRO_VIDEO_RELEASED_AT)
    expect(isPreReleaseAccount(new Date(released - DAY).toISOString())).toBe(true)
    expect(isPreReleaseAccount(new Date(released + DAY).toISOString())).toBe(false)
  })
  it('is false for a missing or unreadable created_at', () => {
    expect(isPreReleaseAccount(undefined)).toBe(false)
    expect(isPreReleaseAccount('nope')).toBe(false)
  })
})

describe('the stall rule', () => {
  it('is twenty seconds', () => {
    expect(INTRO_VIDEO_STALL_MS).toBe(20000)
  })
})

describe('pending and the flag save', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.patch.mockReset()
  })
  const signIn = (user) => {
    useUserStore().currentUser = { id: 'user-1', ...user }
  }

  it('is pending only when the flag is exactly false', () => {
    const intro = useIntroVideo()
    signIn({ intro_video_seen: false })
    expect(intro.pending.value).toBe(true)
    signIn({ intro_video_seen: true })
    expect(intro.pending.value).toBe(false)
    signIn({})
    expect(intro.pending.value).toBe(false)
  })

  it('markSeen saves the flag through the store and stops being pending', async () => {
    h.patch.mockResolvedValue({ data: { intro_video_seen: true } })
    signIn({ id: 'user-2', intro_video_seen: false })
    const intro = useIntroVideo()
    const ok = await intro.markSeen()
    expect(h.patch).toHaveBeenCalledWith({ intro_video_seen: true })
    expect(ok).toBe(true)
    expect(useUserStore().currentUser.intro_video_seen).toBe(true)
    expect(intro.pending.value).toBe(false)
  })

  it('a failed save still closes for this visit and leaves the flag false', async () => {
    h.patch.mockRejectedValue(new Error('network'))
    signIn({ id: 'user-3', intro_video_seen: false })
    const intro = useIntroVideo()
    const ok = await intro.markSeen()
    expect(ok).toBe(false)
    expect(intro.pending.value).toBe(false)
    expect(useUserStore().currentUser.intro_video_seen).toBe(false)
  })
})

describe('a failed save is remembered in this browser', () => {
  const mem = new Map()
  const markKey = (id) => `giljo_banner_dismissals_${id}`
  beforeEach(() => {
    mem.clear()
    window.localStorage = {
      getItem: (k) => (mem.has(k) ? mem.get(k) : null),
      setItem: (k, v) => mem.set(k, String(v)),
      removeItem: (k) => mem.delete(k),
      clear: () => mem.clear(),
    }
    h.patch.mockReset()
  })
  const freshSession = (user) => {
    setActivePinia(createPinia())
    useUserStore().currentUser = { ...user }
    return useIntroVideo()
  }

  it('failed save: the next load shows no pop-up and sends the save again', async () => {
    h.patch.mockRejectedValue(new Error('offline'))
    await freshSession({ id: 'rt-1', intro_video_seen: false }).markSeen()
    expect(mem.get(markKey('rt-1'))).toContain('intro-video:save-pending')

    h.patch.mockReset()
    h.patch.mockRejectedValue(new Error('still offline'))
    const next = freshSession({ id: 'rt-1', intro_video_seen: false })
    await flushPromises()
    expect(next.pending.value).toBe(false)
    expect(h.patch).toHaveBeenCalledTimes(1)
    expect(h.patch).toHaveBeenCalledWith({ intro_video_seen: true })
    expect(mem.get(markKey('rt-1'))).toContain('intro-video:save-pending')
  })

  it('a successful retry clears the mark and sets the flag', async () => {
    h.patch.mockRejectedValue(new Error('offline'))
    await freshSession({ id: 'rt-2', intro_video_seen: false }).markSeen()
    h.patch.mockReset()
    h.patch.mockResolvedValue({ data: { intro_video_seen: true } })
    const next = freshSession({ id: 'rt-2', intro_video_seen: false })
    await flushPromises()
    expect(useUserStore().currentUser.intro_video_seen).toBe(true)
    expect(mem.get(markKey('rt-2')) ?? '').not.toContain('intro-video:save-pending')
    expect(next.pending.value).toBe(false)
  })

  it('another user on the same browser is not affected', async () => {
    h.patch.mockRejectedValue(new Error('offline'))
    await freshSession({ id: 'rt-3', intro_video_seen: false }).markSeen()
    h.patch.mockReset()
    const other = freshSession({ id: 'rt-4', intro_video_seen: false })
    await flushPromises()
    expect(other.pending.value).toBe(true)
    expect(h.patch).not.toHaveBeenCalled()
  })

  it('no mark and no retry when the server already says true', async () => {
    const seen = freshSession({ id: 'rt-5', intro_video_seen: true })
    await flushPromises()
    expect(seen.pending.value).toBe(false)
    expect(h.patch).not.toHaveBeenCalled()
  })
})
