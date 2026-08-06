<template>
  <v-menu
    v-model="menuOpen"
    :close-on-content-click="false"
    :location="compact ? 'right' : 'bottom end'"
    offset="8"
    max-width="400"
  >
    <template v-slot:activator="{ props: menuProps }">
      <!-- Compact: orb style for navbar -->
      <v-badge
        v-if="compact"
        :content="unreadCount"
        :model-value="unreadCount > 0"
        :color="badgeColor"
        overlap
        offset-x="2"
        offset-y="2"
      >
        <div
          v-bind="menuProps"
          class="nav-orb nav-orb--bell"
          :class="notificationBellClass"
          role="button"
          tabindex="0"
          aria-label="View notifications"
        >
          <v-icon size="18">mdi-bell</v-icon>
        </div>
      </v-badge>
      <!-- Default: button style for other contexts -->
      <v-badge
        v-else
        :content="unreadCount"
        :model-value="unreadCount > 0"
        :color="badgeColor"
        overlap
        offset-x="4"
        offset-y="4"
      >
        <v-btn
          v-bind="menuProps"
          icon="mdi-bell"
          variant="text"
          aria-label="View notifications"
          :class="['mr-2', notificationBellClass]"
        ></v-btn>
      </v-badge>
    </template>

    <v-card class="notification-dropdown" elevation="8">
      <!-- Header -->
      <v-card-title class="d-flex align-center justify-space-between py-3 px-4 notification-header">
        <span class="text-body-large font-weight-bold">Notifications</span>
        <v-btn
          v-if="unreadCount > 0"
          variant="text"
          size="small"
          color="primary"
          aria-label="Mark all notifications as read"
          @click="handleMarkAllRead"
        >
          Mark all read
        </v-btn>
      </v-card-title>

      <v-divider />

      <!-- Notification List -->
      <v-list
        v-if="notifications.length > 0"
        class="notification-list scrollbar-thin pa-0"
        lines="two"
      >
        <template v-for="(notification, index) in notifications" :key="notification.id">
          <v-list-item
            :class="[
              'notification-item',
              { 'notification-unread': !notification.read },
              { 'notification-navigable': !!projectIdOf(notification) || !!TYPE_ROUTE_MAP[notification.type] },
            ]"
            :aria-label="getNotificationAriaLabel(notification)"
            @click="handleNotificationClick(notification)"
          >
            <!-- Icon -->
            <template v-slot:prepend>
              <v-icon
                :icon="getNotificationIcon(notification.type)"
                :color="getNotificationColor(notification.type)"
                size="24"
              />
            </template>

            <!-- Content -->
            <v-list-item-title class="notification-title mb-1">
              {{ notification.title }}
            </v-list-item-title>
            <div
              :class="['notification-message', 'text-body-medium', { 'message-truncated': !isExpanded(notification.id) }]"
              @click.stop="toggleExpand(notification.id)"
            >
              {{ getNotificationBody(notification) }}
            </div>
            <v-icon
              size="14"
              class="expand-chevron mt-1"
              :aria-label="isExpanded(notification.id) ? 'Collapse message' : 'Expand message'"
              @click.stop="toggleExpand(notification.id)"
            >
              {{ isExpanded(notification.id) ? 'mdi-chevron-up' : 'mdi-chevron-down' }}
            </v-icon>

            <!-- Handover 0259: Project context link -->
            <div
              v-if="notification.metadata?.project_name"
              class="mt-1"
            >
              <v-chip
                size="x-small"
                variant="tonal"
                color="primary"
                prepend-icon="mdi-folder-outline"
                class="notification-project-chip"
                :aria-label="`View project ${notification.metadata.project_name}`"
                @click.stop="navigateToProject(notification)"
              >
                {{ notification.metadata.project_name }}
              </v-chip>
            </div>

            <!-- NB-2: Per-item dismiss button (IMP-5037a). Stops propagation so
                 the row click (navigate/markRead) handler is NOT triggered. -->
            <button
              :data-test="`dismiss-btn-${notification.id}`"
              class="notification-dismiss-btn"
              type="button"
              :aria-label="`Dismiss notification: ${notification.title}`"
              tabindex="0"
              @click.stop="handleDismiss(notification.id)"
            >
              <v-icon size="16" class="notification-dismiss-icon">mdi-close</v-icon>
            </button>

            <!-- Timestamp and Unread Indicator -->
            <template v-slot:append>
              <div class="d-flex flex-column align-end">
                <span class="text-body-small text-muted-a11y">
                  {{ formatTimestamp(notification) }}
                </span>
                <v-icon
                  v-if="!notification.read"
                  icon="mdi-circle"
                  color="primary"
                  size="8"
                  class="mt-1"
                />
              </div>
            </template>
          </v-list-item>

          <v-divider v-if="index < notifications.length - 1" />
        </template>
      </v-list>

      <!-- Empty State -->
      <div v-else class="notification-empty pa-8 text-center">
        <v-icon icon="mdi-bell-outline" size="48" color="grey-lighten-1" class="mb-3" />
        <div class="text-body-medium text-muted-a11y">No notifications</div>
      </div>
    </v-card>
  </v-menu>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { formatDistanceToNow } from 'date-fns'
import { useNotificationStore } from '@/stores/notifications'
import { useWebSocketStore } from '@/stores/websocket'
import { useUserStore } from '@/stores/user'
import { TYPE_ROUTE_MAP, projectIdOf, projectRouteFor, resolveNotificationRoute } from './notificationRouting'

defineProps({
  compact: {
    type: Boolean,
    default: false,
  },
})

const router = useRouter()
const notificationStore = useNotificationStore()
const wsStore = useWebSocketStore()
const userStore = useUserStore()

const menuOpen = ref(false)
const expandedIds = ref(new Set())
let unsubscribeNotification = null

// Computed properties
const notifications = computed(() => notificationStore.sortedNotifications || [])
const unreadCount = computed(() => notificationStore.unreadCount || 0)
const badgeColor = computed(() => notificationStore.badgeColor || 'error')

// Dynamic bell class based on notification priority
const notificationBellClass = computed(() => {
  if (unreadCount.value === 0) return ''
  const color = badgeColor.value
  if (color === 'warning') return 'notification-bell--warning'
  if (color === 'error') return 'notification-bell--error'
  return 'notification-bell--unread'
})

// Get icon based on notification type
const getNotificationIcon = (type) => {
  const iconMap = {
    agent_health: 'mdi-clock-alert',
    agent_status: 'mdi-robot',
    project_update: 'mdi-folder-edit',
    system_alert: 'mdi-alert-circle',
    connection_lost: 'mdi-wifi-off',
    connection_restored: 'mdi-wifi-check',
    handover: 'mdi-hand-back-right-outline', // FE-9289c: Message Hub "it's your call"
    context_tuning: 'mdi-tune',
    vision_analysis: 'mdi-file-document-check',
    // IMP-5037a Day-1 type
    'api_key.expiring_soon': 'mdi-key-alert',
    success: 'mdi-check-circle',
    error: 'mdi-alert-circle',
    info: 'mdi-information',
    warning: 'mdi-alert',
  }
  return iconMap[type] || 'mdi-bell'
}

// Get color based on notification type
const getNotificationColor = (type) => {
  const colorMap = {
    agent_health: 'warning',
    agent_status: 'info',
    project_update: 'primary',
    system_alert: 'error',
    connection_lost: 'error',
    connection_restored: 'success',
    handover: 'warning', // FE-9289c: the yellow "waiting on you" tone
    context_tuning: 'info',
    vision_analysis: 'success',
    // IMP-5037a Day-1 type
    'api_key.expiring_soon': 'warning',
    success: 'success',
    error: 'error',
    info: 'info',
    warning: 'warning',
  }
  return colorMap[type] || 'default'
}

// Format timestamp to relative time (prefer created_at from server, fall back to timestamp)
const formatTimestamp = (notification) => {
  const ts = notification.created_at || notification.timestamp
  if (!ts) return ''
  try {
    return formatDistanceToNow(new Date(ts), { addSuffix: true })
  } catch (error) {
    console.error('[NotificationDropdown] Error formatting timestamp:', error)
    return ''
  }
}

// Return the displayable message body (server sends body; legacy in-memory uses message)
const getNotificationBody = (notification) => notification.body ?? notification.message ?? ''

// Build descriptive ARIA label for notification items (Handover 0259)
const getNotificationAriaLabel = (notification) => {
  const projectName = notification.metadata?.project_name
  const body = getNotificationBody(notification)
  const base = `${notification.title}: ${body}`
  if (projectName) {
    return `${base}. Click to view project ${projectName}`
  }
  return base
}

// Toggle message expand/collapse using local reactive Set (not object mutation)
const isExpanded = (id) => expandedIds.value.has(id)
const toggleExpand = (id) => {
  const next = new Set(expandedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  expandedIds.value = next
}

// Navigate to the project associated with a notification (Handover 0259).
// FE-9191: route resolution lives in notificationRouting.js — closeout-family
// notifications land on the jobs tab, everything else keeps its target.
const navigateToProject = async (notification) => {
  const route = projectRouteFor(notification)
  if (!route) return

  if (!notification.read) {
    try {
      await notificationStore.markRead(notification.id)
    } catch (error) {
      console.error('[NotificationDropdown] Error marking notification as read:', error)
    }
  }

  menuOpen.value = false
  router.push(route)
}

/**
 * Handle notification click:
 *  1. Mark as read via REST (DB-backed; IMP-5037a)
 *  2. Resolve navigation target via notificationRouting.js (client-side; no
 *     server cta_route): stay-on-page carve-outs, then the type → route map,
 *     then the project-context fallback (closeout family → jobs tab, FE-9191)
 */
const handleNotificationClick = async (notification) => {
  if (!notification.read) {
    try {
      await notificationStore.markRead(notification.id)
    } catch (error) {
      console.error('[NotificationDropdown] Error marking notification as read:', error)
    }
  }

  const route = resolveNotificationRoute(notification)
  if (route) {
    menuOpen.value = false
    router.push(route)
  }
}

/**
 * NB-2 (IMP-5037a): Dismiss a single notification.
 * Calls store.markDismissed (REST PATCH + local removal).
 * Propagation is stopped at the template level (@click.stop) so the row's
 * handleNotificationClick (navigate/markRead) is never triggered.
 */
const handleDismiss = async (id) => {
  try {
    await notificationStore.markDismissed(id)
  } catch (error) {
    console.error('[NotificationDropdown] Error dismissing notification:', error)
  }
}

// Mark all as read — uses local markAllAsRead (no bulk REST endpoint yet; 5037b concern)
const handleMarkAllRead = async () => {
  try {
    await notificationStore.markAllAsRead()
  } catch (error) {
    console.error('[NotificationDropdown] Error marking all as read:', error)
  }
}

// Handle notification:new WS event.
// Filter by user_id: null (broadcast) OR matching current user.
const handleNewNotification = (payload) => {
  const currentUserId = userStore.currentUser?.id
  const eventUserId = payload?.user_id ?? payload?.data?.user_id ?? null
  const eventData = payload?.data ?? payload

  // Accept broadcasts (user_id null) or targeted at current user
  if (eventUserId !== null && eventUserId !== undefined && eventUserId !== currentUserId) {
    return
  }

  notificationStore.handleWsNewNotification(eventData)
}

// Lifecycle hooks
// Note: agent:health_alert events are handled by websocketEventRouter.js (Handover 0424)
onMounted(async () => {
  // Load DB-backed notifications on mount (IMP-5037a)
  try {
    await notificationStore.fetch()
  } catch (error) {
    console.warn('[NotificationDropdown] Failed to fetch notifications on mount:', error)
  }

  // Subscribe to real-time notification:new WS events
  try {
    unsubscribeNotification = wsStore.on('notification:new', handleNewNotification)
  } catch (error) {
    console.warn('[NotificationDropdown] Failed to subscribe to notification:new event:', error)
  }
})

onUnmounted(() => {
  // Cleanup WebSocket subscriptions
  try {
    if (typeof unsubscribeNotification === 'function') {
      unsubscribeNotification()
    }
  } catch (error) {
    console.warn('[NotificationDropdown] Error during cleanup:', error)
  }
})
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;

/* Pulsing glow animation for error notifications (connection lost, system alerts) */
@keyframes notification-pulse-error {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(var(--v-theme-error), 0.6);
  }
  50% {
    box-shadow: 0 0 0 12px rgba(var(--v-theme-error), 0);
  }
}

/* Pulsing glow animation for warning notifications (agent health) */
@keyframes notification-pulse-warning {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(var(--v-theme-warning), 0.6);
  }
  50% {
    box-shadow: 0 0 0 12px rgba(var(--v-theme-warning), 0);
  }
}

.notification-bell--error {
  animation: notification-pulse-error 2s ease-in-out infinite;
  border-radius: 50%;
}

.notification-bell--warning {
  animation: notification-pulse-warning 2s ease-in-out infinite;
  border-radius: 50%;
}

/* Fallback for other notification types */
.notification-bell--unread {
  animation: notification-pulse-error 2s ease-in-out infinite;
  border-radius: 50%;
}

.notification-dropdown {
  width: 440px;
  max-height: 500px;
  display: flex;
  flex-direction: column;
}

/* FE-9229: notification title — wraps instead of clipping.
   Vuetify's .v-list-item-title defaults to `white-space: nowrap` +
   `text-overflow: ellipsis`, and the title column is only ~255px wide inside the
   440px dropdown (the prepend icon and the append timestamp take the rest). The
   enriched taxonomy-led titles ("FE-9229 — <project>: recorded without an
   Implement click") measured 911px against that 255px box, so ~72% of the title
   was invisible. Unset the three clip properties so long titles wrap, and step
   the size down to the design-system body rung while going BOLD so a smaller
   title still reads as the row heading. */
.notification-title {
  font-size: $typography-font-size-body;
  font-weight: 700;
  line-height: 1.35;
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
}

/* Notification message text */
.notification-message {
  color: $color-text-muted;
  /* Sits one rung under the title so the heading still wins the hierarchy — the
     former `text-body-*` classes are undefined no-ops, so this text was silently
     inheriting the 16px root size and out-ranking its own title. */
  font-size: $typography-font-size-small;
  line-height: 1.4;
  cursor: pointer;
}

.notification-message:hover {
  text-decoration: underline;
  text-decoration-style: dotted;
}

/* Message truncation - click to expand */
.message-truncated {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.expand-chevron {
  color: $color-brand-yellow;
  cursor: pointer;
  opacity: 0.8;
  transition: opacity 0.2s ease;
}

.expand-chevron:hover {
  opacity: 1;
}

.notification-header {
  background-color: rgba(var(--v-theme-surface-variant), 0.3);
  flex-shrink: 0;
}

.notification-list {
  max-height: 400px;
  overflow-y: auto;
  flex: 1 1 auto;
}

.notification-item {
  cursor: pointer;
  transition: background-color $transition-normal ease;
  padding: 12px 16px;
}

.notification-item:hover {
  background-color: rgba(var(--v-theme-primary), 0.08);
}

.notification-unread {
  background-color: rgba(var(--v-theme-primary), 0.05);
  border-left: 3px solid rgb(var(--v-theme-primary));
}

/* Handover 0259: Visual affordance for navigable notifications */
.notification-navigable {
  cursor: pointer;
}

.notification-navigable:hover {
  background-color: rgba(var(--v-theme-primary), 0.12);
}

.notification-project-chip {
  cursor: pointer;
}

/* NB-2 (IMP-5037a): Per-item dismiss button — positions top-right inside the list item */
.notification-item {
  position: relative;
}

.notification-dismiss-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  /* Min 44×44 px touch target (WCAG 2.5.5 AAA; 24×24 visible + padding achieves AA) */
  min-width: 32px;
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border: none;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, background-color 0.15s ease;
  /* Use design token for muted color — no hardcoded hex */
  color: $color-text-muted;
  z-index: 1;
}

/* Show dismiss button on item hover or when focused (keyboard navigation) */
.notification-item:hover .notification-dismiss-btn,
.notification-dismiss-btn:focus-visible {
  opacity: 1;
}

.notification-dismiss-btn:hover,
.notification-dismiss-btn:focus-visible {
  background-color: rgba(var(--v-theme-error), 0.12);
  color: rgb(var(--v-theme-error));
  outline: 2px solid rgba(var(--v-theme-error), 0.5);
  outline-offset: 1px;
}

.notification-dismiss-icon {
  pointer-events: none;
}

.notification-empty {
  flex-shrink: 0;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

// Orb style matching NavigationDrawer orbs
.nav-orb {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.25s ease;

  &:hover { transform: scale(1.08); }
  &:active { transform: scale(0.95); }
}

@media (max-width: 1024px) {
  .nav-orb {
    width: 44px;
    height: 44px;
  }
}

.nav-orb--bell {
  background: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.9);

  &:hover { background: rgba(255, 255, 255, 0.18); }
}

</style>
