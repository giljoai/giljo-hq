/**
 * commHubEventRoutes.js — FE-6054e/f Agent Message Hub WebSocket event routes.
 *
 * Routes `thread_message` and `thread_update` WS events to commHubStore actions,
 * then mirrors each event as a CustomEvent on `window` so the
 * useHubNotifications composable can observe without coupling to the router.
 */
import { useCommHubStore } from '../commHubStore'
import { useAgentJobsStore } from '../agentJobsStore'
import { useProjectTabsStore } from '../projectTabs'

function dispatchWindowEvent(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

// FE-9184: a hub post can raise an agent's messages_waiting_count on the open
// project's jobs table, so a thread_message triggers the jobs store's debounced
// count refresh. Scoping: the REST broadcast path stamps project_id, but the
// MCP post path (_comm_tools.py) broadcasts project_id=null even for a
// project-bound thread — fall back to the Hub store's thread directory, and
// refresh anyway when the thread isn't loaded (debounced + count-only, so the
// worst case is one cheap /jobs read) rather than risk a stale badge.
function refreshWaitingCountsForOpenProject(payload, commHub) {
  const currentProjectId = useProjectTabsStore()?.currentProject?.id
  if (!currentProjectId) return

  let messageProjectId = payload?.project_id ?? null
  let resolved = messageProjectId != null
  if (!resolved && payload?.thread_id) {
    const thread = commHub.threadsById?.get?.(payload.thread_id)
    if (thread) {
      messageProjectId = thread.project_id ?? null
      resolved = true
    }
  }

  // Resolved to a standalone (town square) thread or another project's thread
  // → cannot affect this table's counts.
  if (resolved && messageProjectId !== currentProjectId) return

  useAgentJobsStore().refreshMessagesWaitingCounts(currentProjectId)
}

export const COMM_HUB_EVENT_ROUTES = {
  thread_message: {
    handler: async (payload) => {
      const commHub = useCommHubStore()
      // BE-9414: awaited because a truncated long post fetches its full body here.
      // Unawaited, the hydration would race the notification/badge work below and
      // be unobservable to any caller (tests included) that waits on this handler.
      await commHub.handleThreadMessage(payload)
      dispatchWindowEvent('hub:thread_message', payload)
      refreshWaitingCountsForOpenProject(payload, commHub)
    },
  },
  thread_update: {
    handler: async (payload) => {
      const commHub = useCommHubStore()
      commHub.handleThreadUpdate(payload)
      dispatchWindowEvent('hub:thread_update', payload)
      // FE-9184: update_type="read" = an agent drained its messages via
      // get_thread_history(mark_read=True) — its waiting count just dropped.
      if (payload?.update_type === 'read') {
        refreshWaitingCountsForOpenProject(payload, commHub)
      }
    },
  },
}
