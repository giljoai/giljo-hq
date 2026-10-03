import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { isChunkLoadError, maybeReloadForChunkError, __testing } from './chunkReload'


describe('isChunkLoadError', () => {
  it('matches failed dynamic-import / preload / MIME-refusal messages', () => {
    const positives = [
      new Error('Failed to fetch dynamically imported module: https://x/assets/a.js'),
      new Error('error loading dynamically imported module'),
      new Error('Importing a module script failed.'),
      new Error('Unable to preload CSS for /assets/a.css'),
      new Error('Failed to load module script'),
      new Error("Refused to apply style ... MIME type ('text/html')"),
      new Error("Expected a JavaScript module script but the server responded with text/html"),
      'Failed to fetch dynamically imported module',
      { reason: { message: 'failed to fetch dynamically imported module' } },
    ]
    for (const err of positives) {
      expect(isChunkLoadError(err)).toBe(true)
    }
  })

  it('does NOT match ordinary runtime errors or empty input', () => {
    expect(isChunkLoadError(new Error('Cannot read properties of undefined'))).toBe(false)
    expect(isChunkLoadError(new TypeError('x is not a function'))).toBe(false)
    expect(isChunkLoadError('NetworkError when attempting to fetch resource')).toBe(false)
    expect(isChunkLoadError(null)).toBe(false)
    expect(isChunkLoadError(undefined)).toBe(false)
    expect(isChunkLoadError('')).toBe(false)
  })
})

describe('maybeReloadForChunkError', () => {
  let storage
  let reload
  let toast

  beforeEach(() => {
    const map = new Map()
    storage = {
      getItem: (k) => (map.has(k) ? map.get(k) : null),
      setItem: (k, v) => map.set(k, String(v)),
      removeItem: (k) => map.delete(k),
    }
    reload = vi.fn()
    toast = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reloads once and writes a per-path sentinel when none exists', () => {
    const triggered = maybeReloadForChunkError('/projects/42', {
      storage,
      reload,
      toast,
      now: () => 1000,
    })
    expect(triggered).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(toast).not.toHaveBeenCalled()
    expect(storage.getItem(`${__testing.SENTINEL_PREFIX}/projects/42`)).toBe('1000')
  })

  it('does NOT reload again within the window — surfaces a toast instead (no loop)', () => {
    const key = '/projects/42'
    storage.setItem(`${__testing.SENTINEL_PREFIX}${key}`, '1000')
    const triggered = maybeReloadForChunkError(key, {
      storage,
      reload,
      toast,
      now: () => 1000 + __testing.RELOAD_WINDOW_MS - 1,
    })
    expect(triggered).toBe(false)
    expect(reload).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith(__testing.STALE_MESSAGE)
  })

  it('reloads again once the sentinel is stale (older than the window) — new deploy case', () => {
    const key = '/projects/42'
    storage.setItem(`${__testing.SENTINEL_PREFIX}${key}`, '1000')
    const triggered = maybeReloadForChunkError(key, {
      storage,
      reload,
      toast,
      now: () => 1000 + __testing.RELOAD_WINDOW_MS + 1,
    })
    expect(triggered).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(toast).not.toHaveBeenCalled()
  })

  it('isolates the sentinel per path (a reload on one route does not suppress another)', () => {
    maybeReloadForChunkError('/a', { storage, reload, toast, now: () => 1000 })
    const triggered = maybeReloadForChunkError('/b', { storage, reload, toast, now: () => 1001 })
    expect(triggered).toBe(true)
    expect(reload).toHaveBeenCalledTimes(2)
    expect(toast).not.toHaveBeenCalled()
  })

  it('still reloads when sessionStorage throws (private mode) without looping infinitely', () => {
    const throwingStorage = {
      getItem: () => {
        throw new Error('SecurityError')
      },
      setItem: () => {
        throw new Error('SecurityError')
      },
    }
    const triggered = maybeReloadForChunkError('/x', {
      storage: throwingStorage,
      reload,
      toast,
      now: () => 1000,
    })
    expect(triggered).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
  })
})
