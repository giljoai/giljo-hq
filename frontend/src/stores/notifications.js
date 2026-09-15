import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/services/api'
import { useUserStore } from '@/stores/user'
import { projectIdOf } from '@/components/navigation/notificationRouting'
import { SIGNAL_ADVISORY, classifySignal } from '@/stores/notificationSignalRouter'
import { useSettingsStore } from '@/stores/settings'

const LOCAL_NOTIF_MAX_ROWS = 50
const LOCAL_NOTIF_KEY_PREFIX = 'giljo_local_notifications'

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

function clearLocalRows(userId) {
  if (!userId) return
  try {
    localStorage.removeItem(localNotifStorageKey(userId))
  } catch {
    // ignore
  }
}

function normalizeServerNotif(raw) {
  return {
    id: raw.id,
    type: raw.type,
    severity: raw.severity ?? null,
    title: raw.title,
    body: raw.body ?? null,
    message: raw.body ?? raw.message ?? null,
    payload: raw.payload ?? null,
    project_id: raw.project_id ?? null,
    product_id: raw.product_id ?? null,
    read_at: raw.read_at ?? null,
    dismissed_at: raw.dismissed_at ?? null,
    resolved_at: raw.resolved_at ?? null,
    surface: raw.surface ?? null,
    role_filter: raw.role_filter ?? null,
    cta_label: raw.cta_label ?? null,
    cta_route: raw.cta_route ?? null,
    dismissible: raw.dismissible ?? null,
    created_at: raw.created_at ?? null,
    read: raw.read_at !== null && raw.read_at !== undefined,
    timestamp: raw.created_at ?? raw.timestamp ?? new Date().toISOString(),
    ...(raw.metadata != null ? { metadata: raw.metadata } : {}),
  }
}

export const useNotificationStore = defineStore('notifications', () => {
  const notifications = ref([])

  const unreadCount = computed(() => notifications.value.filter((n) => !n.read).length)


  const sortedNotifications = computed(() => {
    const sorted = [...notifications.value]
    sorted.sort((a, b) => {
      const timeA = new Date(a.timestamp ?? a.created_at ?? 0).getTime()
      const timeB = new Date(b.timestamp ?? b.created_at ?? 0).getTime()
      return timeB - timeA
    })
    return sorted
  })

  const bannerNotifications = computed(() => {
    const advisoriesAllowed = useSettingsStore().bannerAdvisoriesInFold
    return notifications.value.filter((n) => {
      if (n.surface !== 'banner' && n.surface !== 'both') return false
      if (n.dismissed_at != null || n.resolved_at != null) return false
      if (advisoriesAllowed) return true
      return classifySignal(n.type)?.kind !== SIGNAL_ADVISORY
    })
  })

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


  function persistLocalRows() {
    const userId = currentUserId()
    if (!userId) return
    saveLocalRows(
      notifications.value.filter((n) => n._local),
      userId,
    )
  }

  function rehydrateLocalRows() {
    const userId = currentUserId()
    if (!userId) return
    for (const row of loadLocalRows(userId)) {
      if (!notifications.value.some((n) => n.id === row.id)) {
        notifications.value.push(row)
      }
    }
  }

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
      console.error('[NotificationStore] Failed to fetch notifications:', error)
    }
  }

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


  function handleWsNewNotification(data) {
    if (!data?.id) return
    const exists = notifications.value.some((n) => n.id === data.id)
    if (exists) return
    notifications.value.push(normalizeServerNotif(data))
  }

  function handleWsUpdatedNotification(data) {
    if (!data?.id) return
    const idx = notifications.value.findIndex((n) => n.id === data.id)
    if (idx === -1) {
      notifications.value.push(normalizeServerNotif(data))
      return
    }
    notifications.value[idx] = normalizeServerNotif(data)
  }

  function handleWsResolvedNotification(data) {
    const ids = Array.isArray(data?.ids) ? data.ids : []
    if (ids.length === 0) return
    const idSet = new Set(ids)
    notifications.value = notifications.value.filter((n) => !idSet.has(n.id))
  }


  function addNotification(notification) {
    const newNotification = {
      id: notification.id || (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`),
      type: notification.type,
      title: notification.title,
      message: notification.message ?? notification.body ?? null,
      timestamp: notification.timestamp || notification.created_at || new Date().toISOString(),
      read: notification.read !== undefined ? notification.read : false,
      _local: true,
      ...(notification.body !== undefined ? { body: notification.body } : {}),
      ...(notification.created_at !== undefined ? { created_at: notification.created_at } : {}),
      ...(notification.severity !== undefined ? { severity: notification.severity } : {}),
      ...(notification.read_at !== undefined ? { read_at: notification.read_at } : {}),
      ...(notification.dismissed_at !== undefined ? { dismissed_at: notification.dismissed_at } : {}),
      ...(notification.payload !== undefined ? { payload: notification.payload } : {}),
      ...(notification.metadata != null ? { metadata: notification.metadata } : {}),
    }

    const exists = notifications.value.some((n) => n.id === newNotification.id)
    if (!exists) {
      notifications.value.push(newNotification)
      persistLocalRows()
    }
  }

  function markAsRead(id) {
    const notification = notifications.value.find((n) => n.id === id)
    if (notification) {
      notification.read = true
      notification.read_at = notification.read_at ?? new Date().toISOString()
    }
  }

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
    notifications.value = notifications.value.filter(
      (n) => projectIdOf(n) !== projectId,
    )
    persistLocalRows()
  }

  function clearAll(userId) {
    notifications.value = []
    clearLocalRows(userId ?? currentUserId())
  }

  rehydrateLocalRows()

  return {
    notifications,

    unreadCount,
    sortedNotifications,
    bannerNotifications,
    activeBannerType,

    fetch,
    markRead,
    markDismissed,
    handleWsNewNotification,
    handleWsUpdatedNotification,
    handleWsResolvedNotification,

    addNotification,
    markAsRead,
    markAllAsRead,
    removeNotification,
    clearForProject,
    clearAll,
  }
})
