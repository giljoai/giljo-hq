/**
 * Notifications store (IMP-5037a Phase 2 — DB-backed bell; FE-9241 persistence)
 *
 * Replaces the prior in-memory-only store with a REST-backed implementation.
 * Server is source of truth: fetch() → GET /api/notifications on mount.
 * Real-time updates via notification:new (merged by id), notification:updated
 * (D16, Headless S3d -- replaces an existing row by id) and
 * notification:resolved (D16 -- drops resolved ids live, so a banner whose
 * condition already cleared server-side does not sit onscreen until refresh)
 * WS events.
 *
 * Preserved from prior store:
 *  - addNotification() — retained as the WS event handler shim (used by
 *    NotificationDropdown via wsStore.on('notification:new', ...) and by
 *    clearForProject / clearAll callers).
 *  - markAsRead() / markAllAsRead() — local-only fallback kept for
 *    in-memory callers (agent_health events that predate DB persistence).
 *  - removeNotification() / clearForProject() / clearAll() — preserved.
 *  - type→icon/color mapping lives in NotificationDropdown (component layer).
 *
 * New exports: fetch(), markRead(id), markDismissed(id), handleWsNewNotification(data)
 *
 * FE-9241 — client-side persistence for `_local` rows:
 * Silent-agent / auto-failed notifications (agent:silent, agent:health_alert,
 * agent:auto_failed — see stores/eventRoutes/agentEventRoutes.js) are emitted
 * via addNotification() and never reach the server `notifications` table, so
 * they need their own persistence + dismiss/read path. addNotification() now
 * tags these rows `_local: true`. `_local` rows are mirrored to a per-user
 * localStorage key (same direct-localStorage idiom as stores/settings.js — no
 * new dependency) so they survive a page reload, and markRead/markDismissed
 * branch on `_local` to mutate in memory + re-persist instead of issuing a
 * REST call against a server row that doesn't exist. fetch() merges rehydrated
 * `_local` rows into the server list instead of replacing it outright.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/services/api'
import { useUserStore } from '@/stores/user'
import { projectIdOf } from '@/components/navigation/notificationRouting'
import { SIGNAL_ADVISORY, classifySignal } from '@/stores/notificationSignalRouter'
import { useSettingsStore } from '@/stores/settings'

// FE-9241: cap the persisted `_local` row set so localStorage can't grow
// unbounded from a chatty silence detector.
const LOCAL_NOTIF_MAX_ROWS = 50
const LOCAL_NOTIF_KEY_PREFIX = 'giljo_local_notifications'

/** Current user id, or null when unauthenticated / pinia not yet active (defensive). */
function currentUserId() {
  try {
    return useUserStore().currentUser?.id ?? null
  } catch {
    return null
  }
}

function localNotifStorageKey(userId) {
  return `${LOCAL_NOTIF_KEY_PREFIX}_${userId}`
}

/** Read this user's persisted `_local` rows from localStorage. Never throws. */
function loadLocalRows(userId) {
  if (!userId) return []
  try {
    const raw = localStorage.getItem(localNotifStorageKey(userId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

/** Write this user's `_local` rows to localStorage, capped. Never throws. */
function saveLocalRows(rows, userId) {
  if (!userId) return
  try {
    localStorage.setItem(
      localNotifStorageKey(userId),
      JSON.stringify(rows.slice(-LOCAL_NOTIF_MAX_ROWS)),
    )
  } catch {
    // localStorage unavailable/full — non-fatal, in-memory state is still correct
  }
}

/** Remove this user's persisted `_local` rows (logout / session clear). */
function clearLocalRows(userId) {
  if (!userId) return
  try {
    localStorage.removeItem(localNotifStorageKey(userId))
  } catch {
    // ignore
  }
}

/** Normalize a raw notification from the server into local store shape. */
function normalizeServerNotif(raw) {
  return {
    // Server fields — preserved verbatim for PATCH response merging
    id: raw.id,
    type: raw.type,
    severity: raw.severity ?? null,
    title: raw.title,
    // Support both body (server) and message (legacy in-memory)
    body: raw.body ?? null,
    message: raw.body ?? raw.message ?? null,
    payload: raw.payload ?? null,
    // BE-9525c: the normalized top-level ids (server's notification:new/REST
    // rows carry these now; None on rows from before the change).
    project_id: raw.project_id ?? null,
    product_id: raw.product_id ?? null,
    read_at: raw.read_at ?? null,
    dismissed_at: raw.dismissed_at ?? null,
    // IMP-5037b Phase 1 fields — banner surface routing
    resolved_at: raw.resolved_at ?? null,
    surface: raw.surface ?? null,
    role_filter: raw.role_filter ?? null,
    cta_label: raw.cta_label ?? null,
    cta_route: raw.cta_route ?? null,
    dismissible: raw.dismissible ?? null,
    created_at: raw.created_at ?? null,
    // Computed convenience flag
    read: raw.read_at !== null && raw.read_at !== undefined,
    // Legacy compat: timestamp used by sortedNotifications fallback
    timestamp: raw.created_at ?? raw.timestamp ?? new Date().toISOString(),
    // Preserve metadata if present (legacy in-memory notifications)
    ...(raw.metadata != null ? { metadata: raw.metadata } : {}),
  }
}

export const useNotificationStore = defineStore('notifications', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const notifications = ref([])

  // ---------------------------------------------------------------------------
  // Getters
  // ---------------------------------------------------------------------------
  const unreadCount = computed(() => notifications.value.filter((n) => !n.read).length)

  // FE-9553 ruling 2: there is no badgeColor any more. It ranked unread rows by
  // severity to pick red / amber / blue for the bell, and the component turned
  // that colour into an infinitely pulsing glow -- which is precisely the
  // "bell alerts" behaviour the ruling removes. Urgency lives in banners
  // exclusively; the bell is the durable archive and keeps a quiet count only.
  // Deleted rather than left unused: its single consumer is gone, and a
  // severity ladder sitting here unread is an invitation to wire it back up.

  const sortedNotifications = computed(() => {
    const sorted = [...notifications.value]
    sorted.sort((a, b) => {
      const timeA = new Date(a.timestamp ?? a.created_at ?? 0).getTime()
      const timeB = new Date(b.timestamp ?? b.created_at ?? 0).getTime()
      return timeB - timeA // Newest first
    })
    return sorted
  })

  /**
   * IMP-5037b: Banner-surface notifications.
   *
   * Returns rows where:
   *  - surface is 'banner' or 'both' (bell-only rows are excluded)
   *  - dismissed_at is null (user has not dismissed this row)
   *  - resolved_at is null (backend has not resolved this row)
   *
   * Role-filter enforcement is server-side; components add a defense-in-depth
   * guard via userHasRole(n.role_filter) before rendering.
   *
   * FE-9553: also honours the "Advisories in the banner fold" preference. When
   * it is off, advisory-class rows are excluded HERE rather than in
   * SystemStatusBanner's own filter -- one decision per preference, read by
   * every display, instead of a filter per consumer that can drift. Off means
   * BELL-ONLY, exactly as the settings card words it: the row stays in
   * `notifications` and still counts toward the unseen counter, it just stops
   * competing for the banner.
   *
   * Actionable rows are deliberately unaffected. Decisions, batons and mentions
   * are always-on by ruling, so this preference must never become a general
   * banner switch -- the classifier decides what is advisory, so a new advisory
   * type is covered automatically and a new actionable one cannot be silenced
   * by accident.
   */
  const bannerNotifications = computed(() => {
    const advisoriesAllowed = useSettingsStore().bannerAdvisoriesInFold
    return notifications.value.filter((n) => {
      if (n.surface !== 'banner' && n.surface !== 'both') return false
      if (n.dismissed_at != null || n.resolved_at != null) return false
      if (advisoriesAllowed) return true
      return classifySignal(n.type)?.kind !== SIGNAL_ADVISORY
    })
  })

  /**
   * IMP-6042: Single highest-precedence active banner type.
   *
   * Precedence order (highest → lowest):
   *   saas.account_deletion_scheduled > saas.subscription_lapsed >
   *   saas.trial_expired > saas.trial_warning
   *
   * Derived from bannerNotifications so dismissed/resolved rows are already
   * excluded. The notification bell (NotificationDropdown) reads
   * bannerNotifications (or sortedNotifications) directly — this getter is a
   * DISPLAY concern only and does NOT suppress rows at the source.
   *
   * Returns the winning type string, or null when no banner rows are active.
   */
  const BANNER_PRECEDENCE = [
    'saas.account_deletion_scheduled',
    'saas.subscription_lapsed',
    'saas.trial_expired',
    'saas.trial_warning',
  ]

  const activeBannerType = computed(() => {
    const active = bannerNotifications.value
    if (active.length === 0) return null
    for (const type of BANNER_PRECEDENCE) {
      if (active.some((n) => n.type === type)) return type
    }
    return null
  })

  // ---------------------------------------------------------------------------
  // Actions — REST-backed
  // ---------------------------------------------------------------------------

  /**
   * FE-9241: persist this store's `_local` rows (with their current read/
   * dismissed state) to the current user's localStorage key. Called after
   * every mutation that touches a `_local` row.
   */
  function persistLocalRows() {
    const userId = currentUserId()
    if (!userId) return
    saveLocalRows(
      notifications.value.filter((n) => n._local),
      userId,
    )
  }

  /**
   * FE-9241: merge this user's persisted `_local` rows into notifications.value
   * (dedup by id). Safe to call repeatedly — a no-op once a row is present.
   */
  function rehydrateLocalRows() {
    const userId = currentUserId()
    if (!userId) return
    for (const row of loadLocalRows(userId)) {
      if (!notifications.value.some((n) => n.id === row.id)) {
        notifications.value.push(row)
      }
    }
  }

  /**
   * Fetch current user's notifications from the server.
   * MERGES server rows with rehydrated `_local` rows (dedup by id) — server
   * rows are authoritative for anything DB-backed, but a full replace here
   * used to flush silent-agent notifications on every reload (FE-9241).
   * Called on component mount and on explicit refresh.
   */
  async function fetch() {
    try {
      const response = await api.notifications.list()
      const serverRows = (response.data ?? []).map(normalizeServerNotif)
      const userId = currentUserId()
      const localRows = [
        ...notifications.value.filter((n) => n._local),
        ...loadLocalRows(userId),
      ]
      const merged = [...serverRows]
      for (const row of localRows) {
        if (!merged.some((n) => n.id === row.id)) merged.push(row)
      }
      notifications.value = merged
    } catch (error) {
      // Fail silently — keep existing notifications to avoid blank bell on transient errors.
      console.error('[NotificationStore] Failed to fetch notifications:', error)
    }
  }

  /**
   * Mark a notification as read.
   * FE-9241: `_local` rows (never persisted server-side) are mutated in
   * memory + re-persisted to localStorage — no REST call, since a PATCH
   * against a client-generated id 404s. Server rows keep the original
   * PATCH /api/notifications/{id}/read round trip.
   */
  async function markRead(id) {
    const idx = notifications.value.findIndex((n) => n.id === id)
    const target = idx !== -1 ? notifications.value[idx] : null

    if (target?._local) {
      target.read = true
      target.read_at = target.read_at ?? new Date().toISOString()
      persistLocalRows()
      return
    }

    try {
      const response = await api.notifications.markRead(id)
      const updated = normalizeServerNotif(response.data)
      if (idx !== -1) {
        notifications.value[idx] = updated
      }
    } catch (error) {
      console.error('[NotificationStore] Failed to mark notification as read:', error)
    }
  }

  /**
   * Mark a notification as dismissed.
   * FE-9241: `_local` rows are removed in memory + re-persisted to
   * localStorage — no REST call (no server row exists to PATCH). Server
   * rows keep the original PATCH /api/notifications/{id}/dismiss round trip.
   */
  async function markDismissed(id) {
    const target = notifications.value.find((n) => n.id === id)

    if (target?._local) {
      notifications.value = notifications.value.filter((n) => n.id !== id)
      persistLocalRows()
      return
    }

    try {
      await api.notifications.markDismissed(id)
      notifications.value = notifications.value.filter((n) => n.id !== id)
    } catch (error) {
      console.error('[NotificationStore] Failed to dismiss notification:', error)
    }
  }

  // ---------------------------------------------------------------------------
  // Actions — WS event handler
  // ---------------------------------------------------------------------------

  /**
   * Handle a notification:new WS event payload.
   * Merges by id — no-op if the notification is already present.
   * Callers should filter by user_id (null=broadcast OR == current user) before calling.
   */
  function handleWsNewNotification(data) {
    if (!data?.id) return
    const exists = notifications.value.some((n) => n.id === data.id)
    if (exists) return
    notifications.value.push(normalizeServerNotif(data))
  }

  /**
   * D16 (Headless S3d): handle a notification:updated WS event payload.
   * Fired when upsert_by_dedupe_key refreshes an already-open row in place
   * (e.g. a scanner's "5 pending migrations" -> "3 pending migrations").
   * Replaces the row by id if present; otherwise behaves like a new row, since
   * an update the client never saw the insert for is indistinguishable from new.
   */
  function handleWsUpdatedNotification(data) {
    if (!data?.id) return
    const idx = notifications.value.findIndex((n) => n.id === data.id)
    if (idx === -1) {
      notifications.value.push(normalizeServerNotif(data))
      return
    }
    notifications.value[idx] = normalizeServerNotif(data)
  }

  /**
   * D16 (Headless S3d): handle a notification:resolved WS event payload.
   * Drops every id in the resolved set from the local list -- a resolved row
   * is never returned by the default GET /api/notifications (include_resolved
   * defaults false), so dropping it here mirrors what a fresh fetch() would
   * already show. This is the fix for "an answered agent question sits on
   * screen until refresh": the banner it fed (bannerNotifications) is a
   * computed over `notifications`, so removing the row here clears it live.
   */
  function handleWsResolvedNotification(data) {
    const ids = Array.isArray(data?.ids) ? data.ids : []
    if (ids.length === 0) return
    const idSet = new Set(ids)
    notifications.value = notifications.value.filter((n) => !idSet.has(n.id))
  }

  // ---------------------------------------------------------------------------
  // Legacy in-memory actions (preserved for backward compat)
  // ---------------------------------------------------------------------------

  /**
   * Add a notification directly (in-memory, no REST call).
   * Retained for callers that emit local events (e.g. agent_health WS events
   * that are not yet persisted in the DB). Deduplicates by id.
   * FE-9241: tagged `_local: true` and mirrored to localStorage so it
   * survives a refresh and its dismiss/read state stays client-side.
   */
  function addNotification(notification) {
    const newNotification = {
      id: notification.id || (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`),
      type: notification.type,
      title: notification.title,
      message: notification.message ?? notification.body ?? null,
      timestamp: notification.timestamp || notification.created_at || new Date().toISOString(),
      read: notification.read !== undefined ? notification.read : false,
      _local: true,
      // Spread optional fields only when present — preserves exact shape for legacy callers
      ...(notification.body !== undefined ? { body: notification.body } : {}),
      ...(notification.created_at !== undefined ? { created_at: notification.created_at } : {}),
      ...(notification.severity !== undefined ? { severity: notification.severity } : {}),
      ...(notification.read_at !== undefined ? { read_at: notification.read_at } : {}),
      ...(notification.dismissed_at !== undefined ? { dismissed_at: notification.dismissed_at } : {}),
      ...(notification.payload !== undefined ? { payload: notification.payload } : {}),
      ...(notification.metadata != null ? { metadata: notification.metadata } : {}),
    }

    // Dedup by id
    const exists = notifications.value.some((n) => n.id === newNotification.id)
    if (!exists) {
      notifications.value.push(newNotification)
      persistLocalRows()
    }
  }

  /** Mark a notification as read locally (no REST call). Preserved for agent_health callers. */
  function markAsRead(id) {
    const notification = notifications.value.find((n) => n.id === id)
    if (notification) {
      notification.read = true
      notification.read_at = notification.read_at ?? new Date().toISOString()
    }
  }

  /**
   * Mark all notifications as read locally (no REST call).
   * FE-9241: re-persists `_local` rows so their new read state survives a refresh.
   */
  function markAllAsRead() {
    notifications.value.forEach((n) => {
      n.read = true
      n.read_at = n.read_at ?? new Date().toISOString()
    })
    persistLocalRows()
  }

  function removeNotification(id) {
    notifications.value = notifications.value.filter((n) => n.id !== id)
    persistLocalRows()
  }

  function clearForProject(projectId) {
    if (!projectId) return
    // BE-9525c: was `n.metadata?.project_id !== projectId` -- rows written in
    // the payload shape (server structured-payload notifications) were never
    // cleared, since their project id lives at n.payload.project_id (or, after
    // this project, the normalized n.project_id). projectIdOf reads all three
    // shapes, preferring the normalized top-level one.
    notifications.value = notifications.value.filter(
      (n) => projectIdOf(n) !== projectId,
    )
    persistLocalRows()
  }

  /**
   * Clear all in-memory notifications and this user's persisted `_local` rows.
   * FE-9241: called from the logout path (stores/user.js) so a different
   * account on the same browser never rehydrates the previous user's
   * client-only notifications. `userId` is accepted explicitly because the
   * logout flow nulls `currentUser` before this runs — pass the outgoing
   * user's id there; other callers (e.g. tests resetting store state) can
   * omit it and fall back to the current user, if any.
   */
  function clearAll(userId) {
    notifications.value = []
    clearLocalRows(userId ?? currentUserId())
  }

  // FE-9241: rehydrate this user's persisted `_local` rows on store init —
  // best-effort; if the user isn't authenticated yet at this point, fetch()
  // rehydrates again on mount once the session is known.
  rehydrateLocalRows()

  return {
    // State
    notifications,

    // Getters
    unreadCount,
    sortedNotifications,
    bannerNotifications,
    activeBannerType,

    // REST-backed actions
    fetch,
    markRead,
    markDismissed,
    handleWsNewNotification,
    handleWsUpdatedNotification,
    handleWsResolvedNotification,

    // Legacy in-memory actions (preserved for backward compat)
    addNotification,
    markAsRead,
    markAllAsRead,
    removeNotification,
    clearForProject,
    clearAll,
  }
})
