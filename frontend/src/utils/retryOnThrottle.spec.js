import { describe, it, expect, vi } from 'vitest'
import { retryOnThrottle } from './retryOnThrottle'

const throttled = (status, retryAfter) => ({
  response: { status, headers: retryAfter === undefined ? {} : { 'retry-after': String(retryAfter) } },
})

describe('retryOnThrottle', () => {
  it('returns the first success without waiting', async () => {
    const sleep = vi.fn()
    const fn = vi.fn().mockResolvedValue('ok')
    await expect(retryOnThrottle(fn, { sleep })).resolves.toBe('ok')
    expect(sleep).not.toHaveBeenCalled()
  })

  it('retries a 429 and honors Retry-After', async () => {
    const sleep = vi.fn().mockResolvedValue()
    const fn = vi.fn().mockRejectedValueOnce(throttled(429, 3)).mockResolvedValue('ok')
    await expect(retryOnThrottle(fn, { sleep })).resolves.toBe('ok')
    const [waited] = sleep.mock.calls[0]
    expect(waited).toBeGreaterThanOrEqual(3000)
    expect(waited).toBeLessThan(3500)
  })

  it('adds jitter on top of Retry-After, never less than the header', async () => {
    const sleep = vi.fn().mockResolvedValue()
    const fn = vi.fn().mockRejectedValueOnce(throttled(429, 3)).mockResolvedValue('ok')
    await retryOnThrottle(fn, { sleep, jitter: () => 120 })
    expect(sleep).toHaveBeenCalledWith(3120)
  })

  it('retries at most 3 times, then rethrows the last error (no request storm)', async () => {
    const sleep = vi.fn(async () => {
      if (sleep.mock.calls.length > 20) throw new Error('storm: still retrying after 20 waits')
    })
    const err = throttled(429, 0)
    const fn = vi.fn().mockRejectedValue(err)
    await expect(retryOnThrottle(fn, { sleep, maxWaitMs: 1000000 })).rejects.toBe(err)
    expect(fn).toHaveBeenCalledTimes(4)
    expect(sleep).toHaveBeenCalledTimes(3)
  })

  it.each([401, 403])('never retries a %i', async (status) => {
    const sleep = vi.fn()
    const err = throttled(status)
    const fn = vi.fn().mockRejectedValue(err)
    await expect(retryOnThrottle(fn, { sleep })).rejects.toBe(err)
    expect(fn).toHaveBeenCalledTimes(1)
    expect(sleep).not.toHaveBeenCalled()
  })

  it('retries a 503', async () => {
    const sleep = vi.fn().mockResolvedValue()
    const fn = vi.fn().mockRejectedValueOnce(throttled(503)).mockResolvedValue('ok')
    await expect(retryOnThrottle(fn, { sleep })).resolves.toBe('ok')
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('does not retry other errors', async () => {
    const sleep = vi.fn()
    const err = throttled(500)
    const fn = vi.fn().mockRejectedValue(err)
    await expect(retryOnThrottle(fn, { sleep })).rejects.toBe(err)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('gives up with the last error once the total wait cap is spent', async () => {
    const waits = []
    const sleep = vi.fn(async (ms) => waits.push(ms))
    const err = throttled(429, 6)
    const fn = vi.fn().mockRejectedValue(err)
    await expect(retryOnThrottle(fn, { sleep, maxWaitMs: 10000 })).rejects.toBe(err)
    expect(waits.reduce((a, b) => a + b, 0)).toBeLessThanOrEqual(10000)
  })
})
