/**
 * settings.notificationPrefs.fe9553.spec.js — FE-9553 M4, the client half.
 *
 * The three notification-model preferences live SERVER-SIDE per user, because
 * the web UI is hosted and settings must follow the user to every machine. That
 * is the opposite of the toast position and duration, which stay in
 * localStorage — so this store now holds both kinds, and the tests below pin
 * that they do not contaminate each other.
 *
 * The failure mode being designed against, and why the fallbacks look the way
 * they do: an undefined preference renders a switch as OFF. A user who sees a
 * switch that looks off "fixes" it by turning it on, and has now written a
 * preference they never had — so a transient network failure would silently
 * rewrite settings. Every read therefore falls back to the RULED DEFAULT rather
 * than to undefined or to false, mirroring the reasoning FE-9555 wrote down for
 * the execution-mode default.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const getNotificationPrefs = vi.hoisted(() => vi.fn())
const updateNotificationPrefs = vi.hoisted(() => vi.fn())

vi.mock('@/services/api', () => ({
  default: {
    settings: {
      getNotificationPrefs,
      updateNotificationPrefs,
      // Present so loadSettings()'s CE-gated config read does not explode.
      get: vi.fn(() => Promise.reject(new Error('not used in this suite'))),
    },
  },
  apiClient: { get: vi.fn(), put: vi.fn() },
}))

import { useSettingsStore } from './settings'

/** The ruled defaults, restated here so a drift in either direction fails. */
const RULED = {
  bannerLifecycleEnabled: true,
  bannerAdvisoriesInFold: true,
  popoutScope: 'all',
}

function serverPayload(overrides = {}) {
  return {
    data: {
      notification_preferences: {
        context_tuning_reminder: true,
        tuning_reminder_threshold: 10,
        banner_lifecycle_enabled: true,
        banner_advisories_in_fold: true,
        popout_scope: 'all',
        ...overrides,
      },
    },
  }
}

describe('notification preferences — reads (FE-9553)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('starts at the ruled defaults before anything is loaded', () => {
    const store = useSettingsStore()

    expect(store.bannerLifecycleEnabled).toBe(RULED.bannerLifecycleEnabled)
    expect(store.bannerAdvisoriesInFold).toBe(RULED.bannerAdvisoriesInFold)
    expect(store.popoutScope).toBe(RULED.popoutScope)
  })

  it('loads what the server holds', async () => {
    getNotificationPrefs.mockResolvedValueOnce(
      serverPayload({ banner_lifecycle_enabled: false, popout_scope: 'actionable' }),
    )
    const store = useSettingsStore()

    await store.loadNotificationPrefs()

    expect(store.bannerLifecycleEnabled).toBe(false)
    expect(store.popoutScope).toBe('actionable')
    // Untouched key keeps its server value.
    expect(store.bannerAdvisoriesInFold).toBe(true)
  })

  it('falls back to the ruled defaults when the read FAILS', async () => {
    getNotificationPrefs.mockRejectedValueOnce(new Error('network'))
    const store = useSettingsStore()

    await store.loadNotificationPrefs()

    // Not undefined, and not false: a failed read must not render as "off".
    expect(store.bannerLifecycleEnabled).toBe(true)
    expect(store.bannerAdvisoriesInFold).toBe(true)
    expect(store.popoutScope).toBe('all')
  })

  it('tolerates a legacy row that carries none of the three keys', async () => {
    // The server merges defaults in, but the client must not assume that: a
    // stale build, a cached response or a partial payload would otherwise land
    // `undefined` in a switch and render it off.
    getNotificationPrefs.mockResolvedValueOnce({
      data: {
        notification_preferences: {
          context_tuning_reminder: true,
          tuning_reminder_threshold: 10,
        },
      },
    })
    const store = useSettingsStore()

    await store.loadNotificationPrefs()

    expect(store.bannerLifecycleEnabled).toBe(true)
    expect(store.bannerAdvisoriesInFold).toBe(true)
    expect(store.popoutScope).toBe('all')
  })

  it('falls back for an UNRECOGNISED popout scope rather than storing it', async () => {
    // The scope is enum-like and the projector treats an unknown value as its
    // safe default, so a typo that reached the store would look saved and then
    // quietly behave as something else.
    getNotificationPrefs.mockResolvedValueOnce(serverPayload({ popout_scope: 'everything' }))
    const store = useSettingsStore()

    await store.loadNotificationPrefs()

    expect(store.popoutScope).toBe('all')
  })
})

describe('notification preferences — writes (FE-9553)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('sends ONLY the key being changed', async () => {
    updateNotificationPrefs.mockResolvedValueOnce(
      serverPayload({ banner_lifecycle_enabled: false }),
    )
    const store = useSettingsStore()

    await store.updateNotificationPrefs({ bannerLifecycleEnabled: false })

    // A full-object write is what clobbers siblings; the backend's per-key
    // guards only help if the client actually sends one key.
    expect(updateNotificationPrefs).toHaveBeenCalledWith({ banner_lifecycle_enabled: false })
  })

  it('mirrors what the server CONFIRMED, not what was sent', async () => {
    // The server validates; a write that was coerced or refused must not leave
    // the control showing a value the account does not hold.
    updateNotificationPrefs.mockResolvedValueOnce(serverPayload({ popout_scope: 'all' }))
    const store = useSettingsStore()

    await store.updateNotificationPrefs({ popoutScope: 'off' })

    expect(store.popoutScope).toBe('all')
  })

  it('maps every client key to its server key', async () => {
    updateNotificationPrefs.mockResolvedValue(serverPayload())
    const store = useSettingsStore()

    await store.updateNotificationPrefs({
      bannerLifecycleEnabled: false,
      bannerAdvisoriesInFold: false,
      popoutScope: 'off',
    })

    expect(updateNotificationPrefs).toHaveBeenCalledWith({
      banner_lifecycle_enabled: false,
      banner_advisories_in_fold: false,
      popout_scope: 'off',
    })
  })

  it('a rejected write leaves the previous value in place', async () => {
    getNotificationPrefs.mockResolvedValueOnce(serverPayload({ popout_scope: 'actionable' }))
    const store = useSettingsStore()
    await store.loadNotificationPrefs()

    updateNotificationPrefs.mockRejectedValueOnce(new Error('boom'))
    await expect(store.updateNotificationPrefs({ popoutScope: 'off' })).rejects.toThrow()

    // Not optimistically applied: the control must keep showing what the
    // account actually holds.
    expect(store.popoutScope).toBe('actionable')
  })
})

describe('the two kinds of setting do not contaminate each other (FE-9553)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('server-side prefs are not written into the localStorage toast settings', async () => {
    getNotificationPrefs.mockResolvedValueOnce(serverPayload({ popout_scope: 'off' }))
    const store = useSettingsStore()

    await store.loadNotificationPrefs()

    // settings.notifications is the localStorage blob for toast position and
    // duration, and its normalizer drops any key it does not know -- so a
    // server pref parked in there would be silently discarded on the next
    // save. Keeping them separate is the point.
    expect(store.settings.notifications).not.toHaveProperty('popout_scope')
    expect(store.settings.notifications).not.toHaveProperty('popoutScope')
    expect(Object.keys(store.settings.notifications).sort()).toEqual(['duration', 'position'])
  })

  it('the toast position and duration still work and are untouched', async () => {
    const store = useSettingsStore()

    await store.updateSettings({ notifications: { position: 'top-left', duration: 9 } })

    expect(store.notificationPosition).toBe('top-left')
    // The getter exposes milliseconds while storage holds seconds.
    expect(store.notificationDuration).toBe(9000)
  })
})
