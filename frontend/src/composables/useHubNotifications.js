/**
 * useHubNotifications.js — FE-6054f
 *
 * Gated, no-spam alerting for the Agent Message Hub.
 *
 * Fires ONLY for user-invoked events:
 *   1. thread_update: next_action_owner === currentUser.id  (PRIMARY — baton handed to operator)
 *   2. thread_message: requires_action === true
 *   3. thread_message: content mentions currentUser.display_name (case-insensitive)
 *
 * Own posts (from_agent_id === currentUser.id) are NEVER signalled.
 *
 * Routing by presence (useHubPresence):
 *   - isHubPresent=true → in-pane cue only, no toast/notification
 *   - isHubPresent=false → toast via useToast + browser Notification (if granted)
 *
 * Permission is requested LAZILY on first qualifying away event.
 * De-duplicates: same signal key does not fire twice until the key changes.
 */
import { onScopeDispose, getCurrentScope } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useCommHubStore } from '@/stores/commHubStore'
import { useNotificationStore } from '@/stores/notifications'
import { useHubPresence } from './useHubPresence'
import { useToast } from './useToast'

export function useHubNotifications() {
  const { showToast } = useToast()
  const { isHubPresent } = useHubPresence()
  const router = useRouter()

  // FE-9289c: the handover deep-links to its thread. HubView reads ?thread=<id> on
  // mount and selects it, so this works from a COLD page (bell clicked while the app is
  // on Dashboard) — route first, HubView selects on arrival.
  function openThread(threadId) {
    if (!threadId) return
    try {
      window.focus()
    } catch {
      // noop — focus can throw in some embeddings
    }
    router.push({ path: '/hub', query: { thread: threadId } }).catch(() => {})
  }

  // A human-readable name for the thread if the store knows it, else the id — the
  // handover payload does not carry the thread's subject, only its id.
  function threadLabel(threadId) {
    const t = useCommHubStore().threadsById?.get?.(threadId)
    return t?.subject || t?.title || `thread ${threadId}`
  }

  // De-dupe: track the last-signalled key so identical back-to-back events don't spam
  const lastSignalledKey = new Set()

  // ── Notification permission (lazy, non-blocking) ──

  let permissionRequested = false

  function requestPermissionLazy() {
    if (typeof Notification === 'undefined') return
    if (Notification.permission !== 'default') return
    if (permissionRequested) return
    permissionRequested = true
    try {
      // Fire-and-forget — we don't block on the result; next event will check permission
      Notification.requestPermission().catch(() => {})
    } catch {
      // Older browsers may not return a promise; ignore
    }
  }

  function fireNotification(title, body, threadId) {
    if (typeof Notification === 'undefined') return
    requestPermissionLazy()
    if (Notification.permission !== 'granted') return
    try {
      const n = new Notification(title, { body, icon: '/Giljo_YW.svg' })
      // FE-9289c: clicking the handover lands on its thread, not just the app.
      n.onclick = () => openThread(threadId)
    } catch {
      // Notification constructor can throw in some environments
    }
  }

  // ── Signal gate ──

  /**
   * Returns a string key for de-duplication, or null if this event should NOT signal.
   */
  function getSignalKey(eventName, payload) {
    const userId = useUserStore().currentUser?.id
    const displayName = useUserStore().currentUser?.display_name

    if (eventName === 'hub:thread_update') {
      // Baton handed to operator — PRIMARY signal
      if (payload.next_action_owner && payload.next_action_owner === userId) {
        return `baton:${payload.thread_id}`
      }
      return null
    }

    if (eventName === 'hub:thread_message') {
      // Own posts are never signalled
      if (payload.from_agent_id === userId) return null

      if (payload.requires_action === true) {
        return `action:${payload.message_id || payload.thread_id}`
      }

      // Mention check — conservative case-insensitive includes
      if (
        displayName &&
        typeof payload.content === 'string' &&
        payload.content.toLowerCase().includes(displayName.toLowerCase())
      ) {
        return `mention:${payload.message_id || payload.thread_id}`
      }
    }

    return null
  }

  function handleEvent(eventName, payload) {
    const key = getSignalKey(eventName, payload)
    if (!key) return

    // De-dupe
    if (lastSignalledKey.has(key)) return
    lastSignalledKey.add(key)

    const threadId = payload.thread_id || ''

    // FE-9289c: a handover (baton to the operator) is the "it's your call" moment —
    // distinct copy from an ordinary mention/action message. "Baton" stays the
    // code-level name; the operator sees "waiting on you".
    const isHandover = eventName === 'hub:thread_update'
    const title = isHandover ? "It's your call" : 'Message Hub'
    const body = isHandover
      ? `${threadLabel(threadId)} — waiting on you`
      : typeof payload.content === 'string'
        ? payload.content.slice(0, 80)
        : 'You have a new message'

    // FE-9289c: a HANDOVER drops a persistent entry in the notification bell, so it
    // survives navigation and the operator can Answer it later from any page. Fed by the
    // same WS event; the row is client-local (useNotificationStore _local shim), deduped
    // by a stable per-thread id so repeated baton events don't stack. Recorded BEFORE the
    // presence gate — the dropdown is the durable record whether or not the operator is
    // in the Hub — while the toast + browser Notification below stay gated on being AWAY.
    if (isHandover && threadId) {
      useNotificationStore().addNotification({
        id: `handover:${threadId}`,
        type: 'handover',
        title,
        body,
        metadata: { thread_id: threadId },
      })
    }

    // In the Hub pane: in-pane cues (the yellow strip) cover it — no toast/push.
    if (isHubPresent.value) return

    showToast({ type: 'info', message: body })
    fireNotification(title, body, threadId)
  }

  function onThreadMessage(e) {
    handleEvent('hub:thread_message', e.detail || {})
  }

  function onThreadUpdate(e) {
    handleEvent('hub:thread_update', e.detail || {})
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('hub:thread_message', onThreadMessage)
    window.addEventListener('hub:thread_update', onThreadUpdate)

    if (getCurrentScope()) {
      onScopeDispose(() => {
        window.removeEventListener('hub:thread_message', onThreadMessage)
        window.removeEventListener('hub:thread_update', onThreadUpdate)
      })
    }
  }

  return {}
}
