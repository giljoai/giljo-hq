import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  ACTIVATE_BREADCRUMB_ARMED_EVENT,
  armActivateBreadcrumb,
  clearActivateBreadcrumb,
  isActivateBreadcrumbArmed,
} from './useTutorialState'

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
