import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const getNotificationPrefs = vi.hoisted(() => vi.fn())
const updateNotificationPrefs = vi.hoisted(() => vi.fn())

vi.mock('@/services/api', () => ({
  default: {
    settings: {
      getNotificationPrefs,
      updateNotificationPrefs,
      get: vi.fn(() => Promise.reject(new Error('not used in this suite'))),
    },
  },
  apiClient: { get: vi.fn(), put: vi.fn() },
}))

import { useSettingsStore } from './settings'

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
    expect(store.bannerAdvisoriesInFold).toBe(true)
  })

  it('falls back to the ruled defaults when the read FAILS', async () => {
    getNotificationPrefs.mockRejectedValueOnce(new Error('network'))
    const store = useSettingsStore()

    await store.loadNotificationPrefs()

    expect(store.bannerLifecycleEnabled).toBe(true)
    expect(store.bannerAdvisoriesInFold).toBe(true)
    expect(store.popoutScope).toBe('all')
  })

  it('tolerates a legacy row that carries none of the three keys', async () => {
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

    expect(updateNotificationPrefs).toHaveBeenCalledWith({ banner_lifecycle_enabled: false })
  })

  it('mirrors what the server CONFIRMED, not what was sent', async () => {
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

    expect(store.settings.notifications).not.toHaveProperty('popout_scope')
    expect(store.settings.notifications).not.toHaveProperty('popoutScope')
    expect(Object.keys(store.settings.notifications).sort()).toEqual(['duration', 'position'])
  })

  it('the toast position and duration still work and are untouched', async () => {
    const store = useSettingsStore()

    await store.updateSettings({ notifications: { position: 'top-left', duration: 9 } })

    expect(store.notificationPosition).toBe('top-left')
    expect(store.notificationDuration).toBe(9000)
  })
})

describe('saved toast settings apply from the moment the store exists', () => {
  const savedBlob = (value) =>
    localStorage.getItem.mockImplementation((key) => (key === 'giljo_settings' ? value : null))

  beforeEach(() => {
    localStorage.getItem.mockReset()
    setActivePinia(createPinia())
  })
  afterEach(() => localStorage.getItem.mockReset())

  it('a fresh store reads the saved duration and position without loadSettings()', () => {
    savedBlob(JSON.stringify({ notifications: { duration: 2, position: 'top-left' } }))

    const store = useSettingsStore()

    expect(store.notificationDuration).toBe(2000)
    expect(store.notificationPosition).toBe('top-left')
  })

  it('a malformed saved blob falls back to the defaults', () => {
    savedBlob('{not json')

    const store = useSettingsStore()

    expect(store.notificationDuration).toBe(5000)
    expect(store.notificationPosition).toBe('bottom-right')
  })
})
