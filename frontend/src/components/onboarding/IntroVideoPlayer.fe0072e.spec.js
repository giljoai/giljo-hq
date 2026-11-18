import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import IntroVideoPlayer from './IntroVideoPlayer.vue'
import { ONBOARDING_INTRO_VIDEO } from '@/content/onboarding/videos'
import { INTRO_VIDEO_STALL_MS } from '@/composables/useIntroVideo'

const mountPlayer = () => mount(IntroVideoPlayer, { props: { video: ONBOARDING_INTRO_VIDEO } })
const videoOf = (w) => w.get('video')

describe('IntroVideoPlayer markup', () => {
  it('is a native video with controls, captions, no autoplay', () => {
    const w = mountPlayer()
    const v = videoOf(w)
    expect(v.attributes('src')).toBe(ONBOARDING_INTRO_VIDEO.video)
    expect(v.attributes('controls')).toBeDefined()
    expect(v.attributes('playsinline')).toBeDefined()
    expect(v.attributes('preload')).toBe('metadata')
    expect(v.attributes('autoplay')).toBeUndefined()
    expect(v.attributes('crossorigin')).toBe('anonymous')
    const track = w.get('track')
    expect(track.attributes('kind')).toBe('captions')
    expect(track.attributes('srclang')).toBe('en')
    expect(track.attributes('default')).toBeDefined()
    expect(track.attributes('src')).toBe(ONBOARDING_INTRO_VIDEO.captions)
  })
})

describe('IntroVideoPlayer events', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('emits ended when the video ends', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('ended')
    expect(w.emitted('ended')).toHaveLength(1)
  })

  it('emits error on a media error', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('error')
    expect(w.emitted('error')).toHaveLength(1)
  })

  it('emits stalled when playback waits for data longer than the stall limit', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('loadedmetadata')
    await videoOf(w).trigger('waiting')
    vi.advanceTimersByTime(INTRO_VIDEO_STALL_MS - 1)
    expect(w.emitted('stalled')).toBeUndefined()
    vi.advanceTimersByTime(2)
    expect(w.emitted('stalled')).toHaveLength(1)
  })

  it('does not emit stalled when playback resumes in time', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('loadedmetadata')
    await videoOf(w).trigger('waiting')
    vi.advanceTimersByTime(5000)
    await videoOf(w).trigger('playing')
    vi.advanceTimersByTime(INTRO_VIDEO_STALL_MS * 3)
    expect(w.emitted('stalled')).toBeUndefined()
  })

  it('a paused video is not a stall', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('loadedmetadata')
    await videoOf(w).trigger('playing')
    await videoOf(w).trigger('pause')
    vi.advanceTimersByTime(INTRO_VIDEO_STALL_MS * 3)
    expect(w.emitted('stalled')).toBeUndefined()
  })

  it('emits stalled when Play was pressed and the video never starts loading', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('play')
    vi.advanceTimersByTime(INTRO_VIDEO_STALL_MS - 1)
    expect(w.emitted('stalled')).toBeUndefined()
    vi.advanceTimersByTime(2)
    expect(w.emitted('stalled')).toHaveLength(1)
  })

  it('the clock starts at Play, not at mount: nothing stalls before Play', () => {
    const w = mountPlayer()
    vi.advanceTimersByTime(INTRO_VIDEO_STALL_MS * 5)
    expect(w.emitted('stalled')).toBeUndefined()
  })

  it('a stall after pressing Play that then plays is cleared', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('play')
    vi.advanceTimersByTime(5000)
    await videoOf(w).trigger('playing')
    vi.advanceTimersByTime(INTRO_VIDEO_STALL_MS * 3)
    expect(w.emitted('stalled')).toBeUndefined()
  })

  it('does not emit stalled for a never-started video that did load metadata', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('play')
    await videoOf(w).trigger('loadedmetadata')
    vi.advanceTimersByTime(INTRO_VIDEO_STALL_MS * 3)
    expect(w.emitted('stalled')).toBeUndefined()
  })

  it('stops watching once it has ended or failed', async () => {
    const w = mountPlayer()
    await videoOf(w).trigger('error')
    vi.advanceTimersByTime(INTRO_VIDEO_STALL_MS * 3)
    expect(w.emitted('stalled')).toBeUndefined()
  })
})
