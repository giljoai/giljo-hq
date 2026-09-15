import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import configService from './configService'

const adminVisible = (isAdmin) =>
  isAdmin && configService.getGiljoMode() === 'ce' && !configService.isFallback()

function okConfig(giljoMode) {
  return {
    ok: true,
    json: async () => ({
      api: { host: 'localhost', port: 8000, protocol: 'http' },
      mode: 'server',
      giljo_mode: giljoMode,
    }),
  }
}

describe('FE-6055 — edition gating fails to "unknown", never "ce"', () => {
  beforeEach(() => {
    configService.clearCache()
    global.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    configService.clearCache()
  })

  it('resolves giljo_mode to "unknown" (never "ce") when the fetch fails', async () => {
    global.fetch.mockRejectedValueOnce(new Error('network down / timeout'))

    const cfg = await configService.fetchConfig()

    expect(cfg._fallback).toBe(true)
    expect(configService.getGiljoMode()).toBe('unknown')
    expect(configService.getGiljoMode()).not.toBe('ce')
  })

  it('hides the admin link on a timed-out (unknown) deployment', async () => {
    global.fetch.mockRejectedValueOnce(new Error('timeout'))
    await configService.fetchConfig()

    expect(adminVisible(true)).toBe(false)
  })

  it('hides the admin link on confirmed SaaS', async () => {
    global.fetch.mockResolvedValueOnce(okConfig('saas'))
    await configService.fetchConfig()

    expect(configService.getGiljoMode()).toBe('saas')
    expect(adminVisible(true)).toBe(false)
  })

  it('shows the admin link only on confirmed CE for an admin', async () => {
    global.fetch.mockResolvedValueOnce(okConfig('ce'))
    await configService.fetchConfig()

    expect(configService.getGiljoMode()).toBe('ce')
    expect(configService.isFallback()).toBe(false)
    expect(adminVisible(true)).toBe(true)
    expect(adminVisible(false)).toBe(false)
  })

  it('keeps the admin link hidden even if a fallback config ever reports "ce"', () => {
    configService.config = { giljo_mode: 'ce', _fallback: true }
    expect(adminVisible(true)).toBe(false)
  })

  it('does NOT pin a fallback config and self-heals to SaaS on the next fetch', async () => {
    global.fetch.mockRejectedValueOnce(new Error('first fetch times out'))
    const first = await configService.fetchConfig()

    expect(first._fallback).toBe(true)
    expect(configService.getRawConfig()).toBeNull()
    expect(global.fetch).toHaveBeenCalledTimes(1)

    global.fetch.mockResolvedValueOnce(okConfig('saas'))
    const second = await configService.fetchConfig()

    expect(global.fetch).toHaveBeenCalledTimes(2)
    expect(second._fallback).toBeUndefined()
    expect(configService.getGiljoMode()).toBe('saas')
    expect(adminVisible(true)).toBe(false)
  })
})
