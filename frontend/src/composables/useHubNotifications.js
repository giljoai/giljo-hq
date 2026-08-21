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
import {
  hubThreadRoute,
  BATON_FOCUS,
  MENTION_FOCUS,
  APPROVAL_FOCUS,
} from '@/components/hub/hubThreadRoute'
import { threadDisplayName } from '@/components/hub/threadDisplayName'
import { useHubPresence } from './useHubPresence'
import { useToast } from './useToast'

/**
 * FE-9439: the badge on a desktop (OS-level) notification.
 *
 * A padded square PNG rather than the app's SVGs, because this slot is not ours: the OS
 * renders it at a size and on a background we do not control, and it letterboxes a
 * non-square source. Solid navy for the same reason — see the note at the call site.
 */
const NOTIFICATION_ICON = '/icons/Giljo_Face_Avatar.png'

/**
 * FE-9436: what the announcer CALLS each reason.
 *
 * The hand-off's title is FE-9289c's, unchanged. The other two shared the generic
 * "Message Hub" because the event name — the only thing the caller had — cannot tell a
 * mention from an approval: both arrive as `thread_message`. The signal gate always
 * knew, and now says so, which is the whole of "one announcer, reason is the only
 * difference" at this layer.
 */
const ANNOUNCER_TITLES = {
  [BATON_FOCUS]: "It's your call",
  [MENTION_FOCUS]: 'You were mentioned',
  [APPROVAL_FOCUS]: 'Needs your approval',
}

/**
 * FE-9436: the durable bell row each reason drops.
 *
 * `type` is what notificationRouting's TYPE_ROUTE_MAP dispatches on. The hand-off's is
 * the bare legacy `handover` and its id stays thread-keyed: these rows live in the
 * browser's own storage, so renaming either would orphan every row a user is already
 * holding. The two new ones are namespaced like the server's types, which is the better
 * convention and costs nothing to adopt for rows that do not exist yet.
 *
 * `keyOnPost` is the substantive difference. A second hand-off in a thread is the SAME
 * standing obligation — answer it — so it collapses onto one row. A second mention is a
 * second thing somebody asked you, and collapsing those loses one of them.
 */
const BELL_ROWS = {
  [BATON_FOCUS]: { type: 'handover', prefix: 'handover', keyOnPost: false },
  [MENTION_FOCUS]: { type: 'hub.mention', prefix: 'mention', keyOnPost: true },
  [APPROVAL_FOCUS]: { type: 'hub.approval', prefix: 'approval', keyOnPost: true },
}

export function useHubNotifications() {
  const { showToast } = useToast()
  const { isHubPresent } = useHubPresence()
  const router = useRouter()

  // FE-9289c: the handover deep-links to its thread. HubView reads ?thread=<id> on
  // mount and selects it, so this works from a COLD page (bell clicked while the app is
  // on Dashboard) — route first, HubView selects on arrival.
  //
  // FE-9418: a HAND-OFF routes through hubThreadRoute(), the same helper the app-wide
  // banner, the Hub's attention strip and both bell rows use, so one baton cannot land
  // in two places depending on which of the four notifications the operator clicked.
  //
  // FE-9436: so does everything else. FE-9418 deliberately left mentions and approvals
  // on a hand-built literal, because the helper could only stamp `focus=baton` and that
  // is what renders "Waiting on you" — a label nobody had handed over. The helper now
  // carries the REASON, so the objection is gone and the last hand-built Hub route on
  // this surface goes with it. One route writer, three reasons.
  function openThread(threadId, { reason = BATON_FOCUS, messageId = null } = {}) {
    if (!threadId) return
    try {
      window.focus()
    } catch {
      // noop — focus can throw in some embeddings
    }
    // A bare id, never the store's thread object — even though the store has one. Its
    // `last_message` is refreshed only by a thread-list read (`handleThreadMessage`
    // bumps last_activity_at and nothing else), so at hand-off time it names whatever
    // was newest when the list was last fetched, NOT the post that handed the baton
    // over. Passing it would pin the operator to a stale message; the tail fallback
    // resolves the real one from the loaded timeline instead.
    //
    // A mention or an approval needs no such fallback: its own event NAMES the post
    // (`thread_message` carries message_id, where the baton's `thread_update` does not),
    // so `messageId` is the live id and never the summary's.
    router.push(hubThreadRoute(threadId, { reason, messageId })).catch(() => {})
  }

  /**
   * What to CALL the thread in the words the operator reads.
   *
   * FE-9436: never its id. This one string reaches three surfaces at once — the toast,
   * the browser notification and the durable bell row — and its old last resort was
   * `thread <uuid>`, which fired precisely when the store had not hydrated the thread:
   * the cold-page, away-from-the-app case the browser notification exists for. So the
   * common case was the one that showed a UUID.
   *
   * The rule itself is shared with the banner and the Hub's own toast, because all three
   * describe the same threads to the same person — see `threadDisplayName`.
   */
  function threadLabel(threadId, payload) {
    return threadDisplayName(useCommHubStore().threadsById?.get?.(threadId), payload)
  }

  /**
   * BE-9414: the body of a long post, not the excerpt the event could carry.
   *
   * A post over ~5.8 KB rides the cross-worker broker as a bounded excerpt
   * (pg_notify caps a NOTIFY payload at 7999 bytes), so testing `payload.content`
   * for the operator's name would silently stop raising the bell for a mention
   * written past the cut-off — the reader would never learn they were named.
   * commHubEventRoutes awaits the store's hydration before dispatching this event,
   * so by now the store holds the full body; fall back to the excerpt only if the
   * hydrating read failed, which is still better than nothing to match against.
   */
  function messageContent(payload) {
    if (!payload?.content_truncated) return payload?.content
    const stored = useCommHubStore()
      .messagesFor?.(payload.thread_id)
      ?.find((m) => m.message_id === payload.message_id)
    return stored?.content ?? payload?.content
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

  function fireNotification(title, body, threadId, { reason, messageId } = {}) {
    if (typeof Notification === 'undefined') return
    requestPermissionLazy()
    if (Notification.permission !== 'granted') return
    try {
      // FE-9439: the AVATAR, not the wordmark. `/Giljo_YW.svg` is the yellow GiljoAI
      // wordmark, which is what the Windows notification popup was showing — a strip of
      // text where every other surface in the app (composer, agent rows, setup wizard,
      // status banner) shows the face. The solid dark-navy PNG is deliberate: notification
      // chrome is a surface we do not control, and the transparent variant loses its light
      // grey eyes against a light-theme OS background.
      const n = new Notification(title, { body, icon: NOTIFICATION_ICON })
      // FE-9289c: clicking the handover lands on its thread, not just the app.
      // FE-9436: and clicking a mention or an approval lands on its POST.
      n.onclick = () => openThread(threadId, { reason, messageId })
    } catch {
      // Notification constructor can throw in some environments
    }
  }

  // ── Signal gate ──

  /**
   * The signal this event raises, or null if it should NOT signal.
   *
   * FE-9436: returns the REASON alongside the de-dup key, rather than leaving the caller
   * to re-derive it from the event name. The gate already knew which of the three it had
   * found — the caller was recomputing a coarser version of the same answer, and only
   * the gate can tell an approval from a mention (both arrive as `thread_message`).
   *
   * `anchor` is the post the reason points at. Only `thread_message` names one; the
   * baton's event carries no message id, which is why a hand-off still resolves to the
   * thread tail. The de-dup keys keep their exact pre-FE-9436 spellings.
   */
  function getSignal(eventName, payload) {
    const userId = useUserStore().currentUser?.id
    const displayName = useUserStore().currentUser?.display_name

    if (eventName === 'hub:thread_update') {
      // Baton handed to operator — PRIMARY signal
      if (payload.next_action_owner && payload.next_action_owner === userId) {
        return { key: `baton:${payload.thread_id}`, reason: BATON_FOCUS, anchor: null }
      }
      return null
    }

    if (eventName === 'hub:thread_message') {
      // Own posts are never signalled
      if (payload.from_agent_id === userId) return null
      const anchor = payload.message_id || null

      if (payload.requires_action === true) {
        return {
          key: `action:${payload.message_id || payload.thread_id}`,
          reason: APPROVAL_FOCUS,
          anchor,
        }
      }

      // Mention check — conservative case-insensitive includes
      const content = messageContent(payload)
      if (
        displayName &&
        typeof content === 'string' &&
        content.toLowerCase().includes(displayName.toLowerCase())
      ) {
        return {
          key: `mention:${payload.message_id || payload.thread_id}`,
          reason: MENTION_FOCUS,
          anchor,
        }
      }
    }

    return null
  }

  function handleEvent(eventName, payload) {
    const signal = getSignal(eventName, payload)
    if (!signal) return
    const { key, reason, anchor } = signal

    // De-dupe
    if (lastSignalledKey.has(key)) return
    lastSignalledKey.add(key)

    const threadId = payload.thread_id || ''

    // FE-9289c: a handover (baton to the operator) is the "it's your call" moment —
    // distinct copy from an ordinary mention/action message. "Baton" stays the
    // code-level name; the operator sees "waiting on you".
    //
    // FE-9436: read off the REASON rather than the event name. Both the mention and the
    // approval arrive as `thread_message`, so the event name could never have told them
    // apart — which is why they shared one title and one landing. Each now says what it
    // is, and that is the only thing separating the three.
    const isHandover = reason === BATON_FOCUS
    const title = ANNOUNCER_TITLES[reason]
    // BE-9296a: name WHO is waiting, not just where. "<thread> — waiting on you" told
    // the operator the one thing they could already see; which agent is blocked is the
    // part that decides whether to answer now. The server resolves the name (it is
    // never self-declared free text) and omits it when the hander is anonymous, so the
    // thread-only wording stays as the fallback rather than rendering "undefined".
    const handedBy = isHandover ? payload.from_display_name : null
    const body = isHandover
      ? handedBy
        ? `${handedBy} is waiting on you in ${threadLabel(threadId, payload)}`
        : `${threadLabel(threadId, payload)} — waiting on you`
      : typeof payload.content === 'string'
        ? payload.content.slice(0, 80)
        : 'You have a new message'

    // FE-9289c: a HANDOVER drops a persistent entry in the notification bell, so it
    // survives navigation and the operator can Answer it later from any page. Fed by the
    // same WS event; the row is client-local (useNotificationStore _local shim), deduped
    // by a stable id so repeated events don't stack. Recorded BEFORE the presence gate —
    // the dropdown is the durable record whether or not the operator is in the Hub —
    // while the toast + browser Notification below stay gated on being AWAY.
    //
    // FE-9436: all three reasons do, per the operator ruling. A mention that disappears
    // when its toast fades is not one surface with the hand-off; it is a lesser one that
    // happens to look similar for four seconds.
    if (threadId) {
      const row = BELL_ROWS[reason]
      useNotificationStore().addNotification({
        id: `${row.prefix}:${row.keyOnPost ? anchor || threadId : threadId}`,
        type: row.type,
        title,
        body,
        // The anchor is what lets a bell row land on the exact post. Omitted rather than
        // set to null for the hand-off, whose event names none — `metadata.message_id`
        // present-but-null would read as a claim the row cannot make.
        metadata: anchor ? { thread_id: threadId, message_id: anchor } : { thread_id: threadId },
      })
    }

    // In the Hub pane: in-pane cues (the yellow strip) cover it — no toast/push.
    if (isHubPresent.value) return

    showToast({ type: 'info', message: body })
    fireNotification(title, body, threadId, { reason, messageId: anchor })
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
