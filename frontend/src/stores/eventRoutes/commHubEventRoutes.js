import { useCommHubStore } from '../commHubStore'
import { useAgentJobsStore } from '../agentJobsStore'
import { useProjectTabsStore } from '../projectTabs'

function dispatchWindowEvent(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

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

  if (resolved && messageProjectId !== currentProjectId) return

  useAgentJobsStore().refreshMessagesWaitingCounts(currentProjectId)
}

export const COMM_HUB_EVENT_ROUTES = {
  thread_message: {
    handler: async (payload) => {
      const commHub = useCommHubStore()
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
      if (payload?.update_type === 'read') {
        refreshWaitingCountsForOpenProject(payload, commHub)
      }
    },
  },
}
