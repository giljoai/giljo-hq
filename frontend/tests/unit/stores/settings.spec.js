/**
 * FE-9000d: settings store -- browser-only persistence regression test.
 *
 * DECIDED scope (2026-07-02): notification prefs live in localStorage
 * only, no server round-trip. The old `api.settings.update` PUT (services/api.js)
 * was triply broken (verb mismatch, body-shape mismatch, no-op backend handler)
 * and is deleted along with both silently-swallowed call sites in this store.
 * This test exercises the failing layer directly: the store's save path must
 * still persist notification prefs to localStorage, and that persistence must
 * survive a fresh store instance (simulating a page reload) with no server
 * dependency at all.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSettingsStore } from '@/stores/settings'

vi.mock('@/services/api', () => ({
  default: {
    settings: {
      get: vi.fn(() => Promise.reject(new Error('not called in this test'))),
      getAgentSilenceThreshold: vi.fn(() =>
        Promise.resolve({ data: { agent_silence_threshold_minutes: 10 } }),
      ),
      updateAgentSilenceThreshold: vi.fn(() =>
        Promise.resolve({ data: { agent_silence_threshold_minutes: 10 } }),
      ),
      getAgentCheckinCadence: vi.fn(() =>
        Promise.resolve({ data: { agent_checkin_cadence_minutes: 20 } }),
      ),
      updateAgentCheckinCadence: vi.fn(() =>
        Promise.resolve({ data: { agent_checkin_cadence_minutes: 25 } }),
      ),
    },
    users: {
      getFieldToggleConfig: vi.fn(() => Promise.resolve({ data: {} })),
    },
  },
}))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn(() => Promise.reject(new Error('config unavailable in test'))),
    getGiljoMode: vi.fn(() => 'ce'),
  },
}))

// Real backing-store localStorage mock (not a bare vi.fn() spy) so a second
// store instance can read back what the first one wrote -- that's the only
// way to prove "survives a reload," not just "setItem was called."
function makeLocalStorageMock() {
  let store = {}
  return {
    getItem: vi.fn((key) => (key in store ? store[key] : null)),
    setItem: vi.fn((key, value) => {
      store[key] = String(value)
    }),
    removeItem: vi.fn((key) => {
      delete store[key]
    }),
    clear: vi.fn(() => {
      store = {}
    }),
  }
}

describe('settings store (FE-9000d)', () => {
  let localStorageMock

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorageMock = makeLocalStorageMock()
    Object.defineProperty(window, 'localStorage', {
      value: localStorageMock,
      configurable: true,
    })
  })

  it('persists updated notification prefs to localStorage with no server call', async () => {
    const store = useSettingsStore()

    await store.updateSettings({ notifications: { position: 'top-left', duration: 8 } })

    expect(store.settings.notifications).toEqual({ position: 'top-left', duration: 8 })
    const raw = localStorageMock.setItem.mock.calls.find((c) => c[0] === 'giljo_settings').at(-1)
    expect(JSON.parse(raw).notifications).toEqual({ position: 'top-left', duration: 8 })
  })

  it('notification prefs survive a fresh store instance (simulated reload)', async () => {
    const firstInstanceStore = useSettingsStore()
    await firstInstanceStore.updateSettings({
      notifications: { position: 'top-center', duration: 12 },
    })

    // Simulate a reload: fresh Pinia (new store instance), same localStorage backing.
    setActivePinia(createPinia())
    const reloadedStore = useSettingsStore()
    await reloadedStore.loadSettings()

    expect(reloadedStore.settings.notifications).toEqual({ position: 'top-center', duration: 12 })
  })

  it('round-trips the account-level check-in cadence through the system settings API (FE-9296b)', async () => {
    const store = useSettingsStore()

    expect(await store.loadAgentCheckinCadence()).toBe(20)
    expect(store.agentCheckinCadenceMinutes).toBe(20)

    expect(await store.updateAgentCheckinCadence(25)).toBe(25)
    expect(store.agentCheckinCadenceMinutes).toBe(25)
  })
})
