import { useAgentJobsStore } from '../agentJobsStore'
import { useLifecycleBannerStore } from '../lifecycleBannerStore'
import { useNotificationStore } from '../notifications'
import { useProductStore } from '../products'
import { useProjectStore } from '../projects'
import { useProjectStateStore } from '../projectStateStore'
import { useTaskStore } from '../tasks'

function announceLifecycleMoment(projectId, moment) {
  try {
    useLifecycleBannerStore().announce({ projectId, moment })
  } catch {
    // lifecycleBannerStore may not be initialized — ignore silently
  }

  if (!projectId) return

  try {
    const store = useLifecycleBannerStore()
    useNotificationStore().addNotification({
      type: 'lifecycle',
      severity: 'info',
      title: 'Project update',
      message: `A project ${store.momentLabel(moment)}`,
      project_id: projectId,
      metadata: { project_id: projectId, moment },
    })
  } catch {
    // The bell is best-effort here for the same reason the banner is: this
    // rides alongside routing that must not break because a store is not up.
  }
}

export const PROJECT_EVENT_ROUTES = {
  project_update: {
    handler: async (payload) => {
      await useProjectStore().handleRealtimeUpdate?.(payload)
      if (payload?.update_type === 'status_changed' && payload?.status === 'active') {
        announceLifecycleMoment(payload?.project_id, 'activated')
      }
    },
  },
  'project:mission_updated': { store: 'projectState', action: 'handleMissionUpdated' },
  'project:staging_complete': {
    handler: async (payload) => {
      try {
        useProjectStateStore().handleStagingComplete?.(payload)
      } catch {
        // projectStateStore may not be initialized — ignore silently
      }
      useProjectStore().debouncedRefreshList?.()
      announceLifecycleMoment(payload?.project_id, 'staging_complete')
    },
  },
  'project:implementation_launched': {
    handler: async (payload) => {
      try {
        const projectStateStore = useProjectStateStore()
        projectStateStore.handleImplementationLaunched?.(payload)
      } catch {
        // projectStateStore may not be initialized — ignore silently
      }
      useProjectStore().debouncedRefreshList?.()
      announceLifecycleMoment(payload?.project_id, 'implementation_launched')
    },
  },
  'project:launched': {
    handler: async (payload) => {
      const projectId = payload?.project_id
      if (projectId) {
        try {
          useProjectStateStore().setLaunched?.(projectId, true)
        } catch {
          // projectStateStore may not be initialized — ignore silently
        }
      }
      useProjectStore().debouncedRefreshList?.()
    },
  },
  'projects:bulk:deactivated': {
    handler: async () => {
      useProjectStore().debouncedRefreshList?.()
    },
  },

  entity_update: {
    handler: async (payload) => {
      if (payload.entity_type === 'task') {
        const productStore = useProductStore()
        const currentProductId = productStore.currentProductId

        if (currentProductId && payload.product_id !== currentProductId) {
          return
        }

        const tasksStore = useTaskStore()
        tasksStore.handleRealtimeUpdate?.(payload)
        return
      }

      if (payload.entity_type === 'agent') {
        const agentJobsStore = useAgentJobsStore()
        agentJobsStore.handleUpdated?.(payload)
        return
      }

      if (payload.entity_type === 'agent_job') {
        useAgentJobsStore().handleUpdated?.(payload)
      }
    },
  },

  'project:created': {
    handler: async () => {
      const projectStore = useProjectStore()
      await projectStore.refreshList()
    },
  },
}
