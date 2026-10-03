import { useLifecycleBannerStore } from '../lifecycleBannerStore'
import { useNotificationStore } from '../notifications'
import { useProjectStore } from '../projects'
import { useProjectStateStore } from '../projectStateStore'

function announceLifecycleMoment(projectId, moment) {
  const store = useLifecycleBannerStore()
  store.announce({ projectId, moment })
  if (!projectId) return
  useNotificationStore().addNotification({
    type: 'lifecycle',
    severity: 'info',
    title: 'Project update',
    message: `A project ${store.momentLabel(moment)}`,
    project_id: projectId,
    metadata: { project_id: projectId, moment },
  })
}

export const PROJECT_EVENT_ROUTES = {
  project_update: {
    handler: async (payload) => {
      await useProjectStore().handleRealtimeUpdate(payload)
      if (payload?.update_type === 'status_changed' && payload?.status === 'active') {
        announceLifecycleMoment(payload?.project_id, 'activated')
      }
    },
  },
  'project:mission_updated': { store: 'projectState', action: 'handleMissionUpdated' },
  'project:staging_complete': {
    handler: async (payload) => {
      useProjectStateStore().handleStagingComplete(payload)
      useProjectStore().debouncedRefreshList()
      announceLifecycleMoment(payload?.project_id, 'staging_complete')
    },
  },
  'project:implementation_launched': {
    handler: async (payload) => {
      useProjectStateStore().handleImplementationLaunched(payload)
      useProjectStore().debouncedRefreshList()
      announceLifecycleMoment(payload?.project_id, 'implementation_launched')
    },
  },
  'project:launched': {
    handler: async (payload) => {
      const projectId = payload?.project_id
      if (projectId) useProjectStateStore().setLaunched(projectId, true)
      useProjectStore().debouncedRefreshList()
    },
  },
  'projects:bulk:deactivated': {
    handler: async () => {
      useProjectStore().debouncedRefreshList()
    },
  },

  'project:created': {
    handler: async () => {
      const projectStore = useProjectStore()
      await projectStore.refreshList()
    },
  },
}
