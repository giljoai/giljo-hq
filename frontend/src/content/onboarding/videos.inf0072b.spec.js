import { describe, it, expect } from 'vitest'
import { MEDIA_HOST, ONBOARDING_LESSONS, ONBOARDING_SETUP_HELPER } from './videos.js'

const EXPECTED = {
  lesson01: [4, '780e1524b25719b600e742d643b67ef3765625b5f3ae8de61b2bf00e01ea642c'],
  lesson02: [2, '1247859090e35fb2146105b18f99248553051ed8cd64aa8fa7d1d3c54e7b0145'],
  lesson03: [5, 'f1496a55fede92eca0f4d81eed879b57fd406b3dfa786608e19d71ad0d8d9235'],
  lesson04: [7, '385490ae3a31f6119b2e168469f2178368d5020ad8bb45408728a24df460a74d'],
  setup: [1, '10804cd090f533a46aabc17c45a765b5449373d6641fcf5c6ca64ea5b7ac3427'],
}

const ALL = [...ONBOARDING_LESSONS, ONBOARDING_SETUP_HELPER]

describe('onboarding video registry', () => {
  it('names the one media host', () => {
    expect(MEDIA_HOST).toBe('https://giljo.ai')
  })

  it('has four lessons and one setup helper, kept apart', () => {
    expect(ONBOARDING_LESSONS.map((v) => v.id)).toEqual([
      'lesson01',
      'lesson02',
      'lesson03',
      'lesson04',
    ])
    expect(ONBOARDING_SETUP_HELPER.id).toBe('setup')
    expect(ALL).toHaveLength(5)
  })

  it.each(Object.entries(EXPECTED))(
    '%s has the delivered version and checksum',
    (id, [version, sha]) => {
      const entry = ALL.find((v) => v.id === id)
      expect(entry.version).toBe(version)
      expect(entry.sha256).toBe(sha)
      expect(entry.sha256).toMatch(/^[0-9a-f]{64}$/)
    },
  )

  it('addresses are the host plus the versioned name, with no query string', () => {
    for (const v of ALL) {
      expect(v.video).toBe(`https://giljo.ai/media/onboarding/${v.id}.v${v.version}.mp4`)
      expect(v.captions).toBe(`https://giljo.ai/media/onboarding/${v.id}.v${v.version}.vtt`)
      expect(v.video.startsWith(`${MEDIA_HOST}/`)).toBe(true)
      expect(v.captions.startsWith(`${MEDIA_HOST}/`)).toBe(true)
      expect(v.video).toMatch(/^https:\/\/giljo\.ai\/media\/onboarding\/[a-z0-9]+\.v\d+\.mp4$/)
      expect(v.captions).toMatch(/^https:\/\/giljo\.ai\/media\/onboarding\/[a-z0-9]+\.v\d+\.vtt$/)
    }
  })

  it('has a title, a length in seconds and a transcript for every entry', () => {
    for (const v of ALL) {
      expect(typeof v.title).toBe('string')
      expect(v.title.length).toBeGreaterThan(0)
      expect(typeof v.seconds).toBe('number')
      expect(v.seconds).toBeGreaterThan(30)
      expect(v.seconds).toBeLessThan(70)
      expect(v.transcript.trim().length).toBeGreaterThan(300)
    }
  })

  it('is frozen', () => {
    expect(Object.isFrozen(ONBOARDING_LESSONS)).toBe(true)
    expect(Object.isFrozen(ONBOARDING_SETUP_HELPER)).toBe(true)
  })
})
