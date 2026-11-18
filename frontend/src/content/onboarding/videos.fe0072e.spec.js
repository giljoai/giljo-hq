import { describe, it, expect } from 'vitest'
import {
  ONBOARDING_INTRO_VIDEO,
  ONBOARDING_LESSONS,
  ONBOARDING_SETUP_HELPER,
} from './videos.js'

describe('intro video registry entry', () => {
  it('has the delivered address, version, length and checksums', () => {
    expect(ONBOARDING_INTRO_VIDEO.id).toBe('how-to-get-going')
    expect(ONBOARDING_INTRO_VIDEO.title).toBe('How to get going')
    expect(ONBOARDING_INTRO_VIDEO.version).toBe(1)
    expect(ONBOARDING_INTRO_VIDEO.seconds).toBe(108.233)
    expect(ONBOARDING_INTRO_VIDEO.sha256).toBe(
      '8758aaca95c422ebc4ba7911c6bd87a5d5097a7a7de9111d18b73ea2ab2ddc57',
    )
    expect(ONBOARDING_INTRO_VIDEO.captionsSha256).toBe(
      'b404ad46ec375ad3faa4844bf87d87d1bbd141ac0d3853dad8cccd0709816217',
    )
    expect(ONBOARDING_INTRO_VIDEO.video).toBe(
      'https://giljo.ai/media/onboarding/how-to-get-going.v1.mp4',
    )
    expect(ONBOARDING_INTRO_VIDEO.captions).toBe(
      'https://giljo.ai/media/onboarding/how-to-get-going.v1.vtt',
    )
  })

  it('carries the narration exactly as scripted', () => {
    const t = ONBOARDING_INTRO_VIDEO.transcript
    expect(t.startsWith("Let's get connected. You bring your AI.")).toBe(true)
    expect(t).toContain('“Can you see Giljo HQ?”')
    expect(t.endsWith('For more Giljo HQ videos, visit giljo.ai.\n')).toBe(true)
    expect(t.split('\n\n')).toHaveLength(14)
  })

  it('is frozen and not mixed into the lessons or the setup helper', () => {
    expect(Object.isFrozen(ONBOARDING_INTRO_VIDEO)).toBe(true)
    expect(ONBOARDING_LESSONS.some((v) => v.id === ONBOARDING_INTRO_VIDEO.id)).toBe(false)
    expect(ONBOARDING_SETUP_HELPER.id).not.toBe(ONBOARDING_INTRO_VIDEO.id)
  })
})
