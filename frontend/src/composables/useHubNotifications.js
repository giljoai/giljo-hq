import { onScopeDispose, getCurrentScope, watch } from 'vue'
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
import { popoutTag } from '@/utils/popoutTag'
import { registerPopout } from '@/utils/popoutRegistry'
import { useSettingsStore } from '@/stores/settings'

import { useThreadPostAttention } from './useThreadPostAttention'

const NOTIFICATION_ICON = '/icons/Giljo_Face_Avatar.png'

const ANNOUNCER_TITLES = {
  [BATON_FOCUS]: "It's your call",
  [MENTION_FOCUS]: 'You were mentioned',
  [APPROVAL_FOCUS]: 'Needs your approval',
}

const QUIET_BELL_TITLES = {
  [APPROVAL_FOCUS]: 'Open ask from an agent',
}

const BELL_ROWS = {
  [BATON_FOCUS]: { type: 'handover', prefix: 'handover', keyOnPost: false },
  [MENTION_FOCUS]: { type: 'hub.mention', prefix: 'mention', keyOnPost: true },
  [APPROVAL_FOCUS]: { type: 'hub.approval', prefix: 'approval', keyOnPost: true },
}

export function useHubNotifications() {
  const router = useRouter()
  const { mentions, ensureLoaded } = useThreadPostAttention()

  ensureLoaded()

  function openThread(threadId, { reason = BATON_FOCUS, messageId = null } = {}) {
    if (!threadId) return
    try {
      window.focus()
    } catch {
      // noop — focus can throw in some embeddings
    }
    router.push(hubThreadRoute(threadId, { reason, messageId })).catch(() => {})
  }

  function threadLabel(threadId, payload) {
    return threadDisplayName(useCommHubStore().threadsById?.get?.(threadId), payload)
  }


  const lastSignalledKey = new Set()


  let permissionRequested = false

  function requestPermissionLazy() {
    if (typeof Notification === 'undefined') return
    if (Notification.permission !== 'default') return
    if (permissionRequested) return
    permissionRequested = true
    try {
      Notification.requestPermission().catch(() => {})
    } catch {
      // Older browsers may not return a promise; ignore
    }
  }

  function fireNotification(title, body, threadId, { reason, messageId } = {}) {
    if (typeof Notification === 'undefined') return

    if (useSettingsStore().popoutScope === 'off') return

    requestPermissionLazy()
    if (Notification.permission !== 'granted') return
    try {
      const tag = popoutTag(reason, threadId)
      const n = new Notification(title, { body, icon: NOTIFICATION_ICON, tag })
      n.onclick = () => openThread(threadId, { reason, messageId })

      registerPopout(tag, n)
    } catch {
      // Notification constructor can throw in some environments
    }
  }


  function getSignal(eventName, payload) {
    const userId = useUserStore().currentUser?.id

    if (eventName === 'hub:thread_update') {
      if (payload.next_action_owner && payload.next_action_owner === userId) {
        return { key: `baton:${payload.thread_id}`, reason: BATON_FOCUS, anchor: null }
      }
      return null
    }

    if (eventName === 'hub:thread_message') {
      if (payload.from_agent_id === userId) return null
      const anchor = payload.message_id || null

      if (payload.requires_action === true) {
        const directedElsewhere = !!payload.to_participant && payload.to_participant !== userId
        if (directedElsewhere) return null
        return {
          key: `action:${payload.message_id || payload.thread_id}`,
          reason: APPROVAL_FOCUS,
          anchor,
          quiet: !payload.to_participant,
        }
      }

    }

    return null
  }

  function handleEvent(eventName, payload) {
    const signal = getSignal(eventName, payload)
    if (!signal) return
    const { key, reason, anchor, quiet } = signal

    if (lastSignalledKey.has(key)) return
    lastSignalledKey.add(key)

    const threadId = payload.thread_id || ''

    const isHandover = reason === BATON_FOCUS
    const title = (quiet && QUIET_BELL_TITLES[reason]) || ANNOUNCER_TITLES[reason]
    const handedBy = isHandover ? payload.from_display_name : null
    const body = isHandover
      ? handedBy
        ? `${handedBy} is waiting on you in ${threadLabel(threadId, payload)}`
        : `${threadLabel(threadId, payload)} — waiting on you`
      : typeof payload.content === 'string'
        ? payload.content.slice(0, 80)
        : 'You have a new message'

    if (threadId) {
      const row = BELL_ROWS[reason]
      useNotificationStore().addNotification({
        id: `${row.prefix}:${row.keyOnPost ? anchor || threadId : threadId}`,
        type: row.type,
        title,
        body,
        metadata: anchor ? { thread_id: threadId, message_id: anchor } : { thread_id: threadId },
      })
    }

    if (quiet) return

    if (!document.hidden) return

    fireNotification(title, body, threadId, { reason, messageId: anchor })
  }


  const announcedMentions = new Set()

  watch(
    mentions,
    (list) => {
      if (!list) return

      for (const entry of list) {
        const threadId = entry?.thread_id
        if (!threadId) continue

        const fresh = (entry.message_ids || []).filter((id) => id && !announcedMentions.has(id))
        if (!fresh.length) continue
        for (const id of fresh) announcedMentions.add(id)

        const title = ANNOUNCER_TITLES[MENTION_FOCUS]
        const body = `You were mentioned in ${threadLabel(threadId, {})}`

        for (const id of fresh) {
          useNotificationStore().addNotification({
            id: `${BELL_ROWS[MENTION_FOCUS].prefix}:${id}`,
            type: BELL_ROWS[MENTION_FOCUS].type,
            title,
            body,
            metadata: { thread_id: threadId, message_id: id },
          })
        }

        if (document.hidden) {
          fireNotification(title, body, threadId, { reason: MENTION_FOCUS, messageId: fresh[0] })
        }
      }
    },
    { immediate: true },
  )

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
