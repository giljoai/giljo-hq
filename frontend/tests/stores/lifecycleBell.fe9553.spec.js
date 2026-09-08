/**
 * lifecycleBell.fe9553.spec.js — FE-9553 M4, the toggles and the missing record.
 *
 * Two claims, and the second one is a defect this milestone exposed rather than
 * created.
 *
 * THE TOGGLES GATE THEIR SURFACES. The settings card offers "Lifecycle events
 * on/off" and "Advisories in the banner fold on/off", and the project's DoD
 * requires each to be PROVEN to gate its surface -- flip it, show the event
 * stops. Both are gated at the SOURCE rather than in the banner component's row
 * filter: lifecycle in lifecycleBannerStore.announce, advisories in the
 * notification store's bannerNotifications getter. One decision per preference,
 * read by every display, instead of a filter per consumer -- and it keeps this
 * work out of SystemStatusBanner.vue.
 *
 * A LIFECYCLE EVENT USED TO LIVE ON ZERO DURABLE SURFACES. projectEventRoutes
 * announced a banner row and wrote no bell row at all, so an unwatched
 * lifecycle banner expired and nothing recorded that the project had been
 * staged. That already contradicted ruling 1 ("missed informational events go
 * to the bell") before any toggle existed; with a toggle it would have become a
 * control that lies, since "off" would have meant "gone" rather than
 * "bell-only". Decided: the path ALWAYS writes a bell row and the
 * toggle gates only the banner. So the visible consequence -- a bell that fills
 * with lifecycle rows -- is deliberate, and it is what "the bell remembers"
 * means. M3's quiet counter is what makes it tolerable.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { id: 'user-1', tenant_key: 'tk_1' } }),
}))

vi.mock('@/services/api', () => ({
  default: { settings: { get: vi.fn(() => Promise.reject(new Error('unused'))) } },
  apiClient: { get: vi.fn(), put: vi.fn() },
}))

import { useLifecycleBannerStore } from '@/stores/lifecycleBannerStore'
import { useNotificationStore } from '@/stores/notifications'
import { useSettingsStore } from '@/stores/settings'
import { routeWebsocketEvent, EVENT_MAP } from '@/stores/websocketEventRouter'

const STAGED = {
  type: 'project:staging_complete',
  data: { project_id: 'proj-1' },
}

/** Drive the REAL router pass, so this exercises the production path. */
async function routeStaged(payload = STAGED) {
  return routeWebsocketEvent(payload, {
    eventMap: EVENT_MAP,
    storeRegistry: {},
    shouldRoute: () => true,
  })
}

describe('FE-9553: the lifecycle banner toggle gates the BANNER only', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('announces a banner row when lifecycle banners are ON (the default)', () => {
    const banner = useLifecycleBannerStore()

    banner.announce({ projectId: 'proj-1', moment: 'staging_complete' })

    expect(banner.rows).toHaveLength(1)
    expect(banner.rows[0].moment).toBe('staging_complete')
  })

  it('announces NO banner row when the user has lifecycle banners OFF', () => {
    const settings = useSettingsStore()
    settings.bannerLifecycleEnabled = false
    const banner = useLifecycleBannerStore()

    banner.announce({ projectId: 'proj-1', moment: 'staging_complete' })

    expect(banner.rows).toEqual([])
  })

  it('the toggle is not a one-way door -- turning it back on announces again', () => {
    // A gate that latches would be worse than no gate: the operator flips it
    // back and nothing returns, so they conclude the setting is broken.
    const settings = useSettingsStore()
    const banner = useLifecycleBannerStore()

    settings.bannerLifecycleEnabled = false
    banner.announce({ projectId: 'proj-1', moment: 'staging_complete' })
    expect(banner.rows).toEqual([])

    settings.bannerLifecycleEnabled = true
    banner.announce({ projectId: 'proj-2', moment: 'activated' })
    expect(banner.rows).toHaveLength(1)
  })
})

describe('FE-9553: a lifecycle event ALWAYS lands in the bell', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('writes a durable bell row when the banner is ON', async () => {
    const notifications = useNotificationStore()

    await routeStaged()

    const rows = notifications.notifications.filter((n) => n.type === 'lifecycle')
    expect(rows).toHaveLength(1)
    expect(rows[0].project_id ?? rows[0].metadata?.project_id).toBe('proj-1')
  })

  it('STILL writes the bell row when the banner is OFF -- off means bell-only, not gone', async () => {
    // The whole point of ruling (A). If this fails, the toggle is a control
    // that lies: it would delete the record rather than relocate it.
    const settings = useSettingsStore()
    settings.bannerLifecycleEnabled = false
    const banner = useLifecycleBannerStore()
    const notifications = useNotificationStore()

    await routeStaged()

    expect(banner.rows).toEqual([])
    expect(notifications.notifications.filter((n) => n.type === 'lifecycle')).toHaveLength(1)
  })

  it('a REPEATED moment for the same project is a second row, not a replacement', async () => {
    // This assertion is the inverse of an earlier draft, and it is right to
    // challenge it. I had keyed the bell row on `lifecycle:<project>:<moment>`
    // so a repeat would dedupe -- which quietly collapses a project that is
    // activated, parked, and activated again into ONE row, losing a dated
    // fact from what the model calls the durable archive. An archive that
    // silently drops repeats is an archive that lies.
    //
    // The in-repo precedent is BELL_ROWS in useHubNotifications: keyOnPost is
    // false for a baton, because a second hand-off is the SAME standing
    // obligation, and true for a mention, because a second mention is a second
    // thing somebody asked. A lifecycle moment is a dated fact, not a standing
    // obligation, so it behaves like the mention.
    //
    // The cost, stated rather than hidden: the payload carries no event id and
    // no timestamp (project_helpers.py builds it), so there is nothing stable
    // to dedupe a genuine double-delivery on. The row is therefore keyed on
    // receipt, exactly as lifecycleBannerStore already keys its banner rows,
    // and one event delivered twice would produce two rows. That is the safer
    // failure of the two: a duplicate is noise, a dropped fact is a lie. Low
    // exposure in practice, because reconnect resync refetches over REST
    // rather than replaying WebSocket events.
    const notifications = useNotificationStore()

    await routeStaged()
    await routeStaged()

    expect(notifications.notifications.filter((n) => n.type === 'lifecycle')).toHaveLength(2)
  })

  it('a DIFFERENT moment on the same project is its own row', async () => {
    const notifications = useNotificationStore()

    await routeStaged()
    await routeStaged({ type: 'project:implementation_launched', data: { project_id: 'proj-1' } })

    expect(
      notifications.notifications.filter((n) => n.type === 'lifecycle').length,
    ).toBeGreaterThanOrEqual(2)
  })

  // CHECKER-MUST-FIRE. Every assertion above depends on the router pass
  // actually reaching the lifecycle path. If the event type were wrong, or the
  // route removed, the "no banner row" assertions would pass for the wrong
  // reason and the bell assertions would fail confusingly. This proves the
  // route under test exists and is wired.
  it('the event type used by this suite is genuinely in the router map', () => {
    expect(EVENT_MAP['project:staging_complete']).toBeDefined()
    expect(EVENT_MAP['project:implementation_launched']).toBeDefined()
  })
})

describe('FE-9553: the advisories toggle gates the banner fold, never the bell', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  /** A server-shaped advisory row that would normally reach the banner. */
  function advisory() {
    return {
      id: 'notif-adv',
      type: 'system.update_available',
      severity: 'info',
      title: 'Update available',
      body: 'A new version is available',
      surface: 'both',
      read_at: null,
      dismissed_at: null,
      resolved_at: null,
      created_at: '2026-09-04T00:00:00Z',
    }
  }

  it('an advisory reaches the banner fold by default', () => {
    const notifications = useNotificationStore()
    notifications.notifications = [advisory()]

    expect(notifications.bannerNotifications.map((n) => n.id)).toContain('notif-adv')
  })

  it('an advisory is excluded from the banner fold when the preference is OFF', () => {
    const settings = useSettingsStore()
    settings.bannerAdvisoriesInFold = false
    const notifications = useNotificationStore()
    notifications.notifications = [advisory()]

    expect(notifications.bannerNotifications.map((n) => n.id)).not.toContain('notif-adv')
  })

  it('and it is STILL in the bell -- off means bell-only', () => {
    // Same rule as the lifecycle toggle, and the settings card says it in
    // words: "off = advisories are bell-only".
    const settings = useSettingsStore()
    settings.bannerAdvisoriesInFold = false
    const notifications = useNotificationStore()
    notifications.notifications = [advisory()]

    expect(notifications.sortedNotifications.map((n) => n.id)).toContain('notif-adv')
    expect(notifications.unreadCount).toBe(1)
  })

  it('an ACTIONABLE row is untouched by the advisories preference', () => {
    // The preference must not become a general banner switch. Decisions and
    // batons are always-on by ruling, so a row that is not advisory has to
    // survive the filter regardless.
    const settings = useSettingsStore()
    settings.bannerAdvisoriesInFold = false
    const notifications = useNotificationStore()
    notifications.notifications = [
      advisory(),
      { ...advisory(), id: 'notif-act', type: 'closeout.approval_required' },
    ]

    const ids = notifications.bannerNotifications.map((n) => n.id)
    expect(ids).toContain('notif-act')
    expect(ids).not.toContain('notif-adv')
  })
})
