/**
 * useTutorialState.breadcrumb.spec.js — FE-9320
 *
 * The other half of the activate-nudge fix. SystemStatusBanner.spec.js proves
 * the banner reacts to the arming event; this proves arming actually EMITS it.
 * Without both halves each side could pass against a broken whole: the banner
 * listening for an event nobody sends, or the composable announcing to nobody.
 *
 * NOTE ON THE HARNESS: tests/setup.js replaces window.localStorage with plain
 * vi.fn() stubs (getItem always returns undefined), so these tests assert the
 * CALLS this module makes rather than a value round-tripping through storage —
 * a round-trip assertion cannot pass here, and "storage unavailable" has to be
 * simulated on that stub, not on Storage.prototype.
 *
 * Edition scope: Both (shared frontend/src).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  ACTIVATE_BREADCRUMB_ARMED_EVENT,
  armActivateBreadcrumb,
  clearActivateBreadcrumb,
  isActivateBreadcrumbArmed,
} from './useTutorialState'

// Imported, never re-declared. A local copy of this string would let the emit
// and the listener drift apart with both sides' specs still green.
const EVENT = ACTIVATE_BREADCRUMB_ARMED_EVENT
const KEY = 'giljo_tutorial_activate_breadcrumb'

describe('armActivateBreadcrumb (FE-9320)', () => {
  let heard

  beforeEach(() => {
    vi.clearAllMocks()
    heard = vi.fn()
    window.addEventListener(EVENT, heard)
  })

  afterEach(() => {
    window.removeEventListener(EVENT, heard)
  })

  it('persists the flag AND announces the arming so long-lived listeners can re-read it', () => {
    armActivateBreadcrumb()

    expect(localStorage.setItem).toHaveBeenCalledWith(KEY, '1')
    expect(heard).toHaveBeenCalledTimes(1)
  })

  it('still announces when localStorage is unavailable (the nudge shows this session)', () => {
    localStorage.setItem.mockImplementationOnce(() => {
      throw new Error('storage disabled')
    })

    expect(() => armActivateBreadcrumb()).not.toThrow()
    expect(heard).toHaveBeenCalledTimes(1)
  })

  it('clearing retires the flag', () => {
    clearActivateBreadcrumb()
    expect(localStorage.removeItem).toHaveBeenCalledWith(KEY)
  })

  it('reads the armed state from storage', () => {
    localStorage.getItem.mockReturnValueOnce('1')
    expect(isActivateBreadcrumbArmed()).toBe(true)

    localStorage.getItem.mockReturnValueOnce(null)
    expect(isActivateBreadcrumbArmed()).toBe(false)
  })
})
