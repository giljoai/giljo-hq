import { useAgentJobsStore } from '../agentJobsStore'
import { useLifecycleBannerStore } from '../lifecycleBannerStore'
import { useNotificationStore } from '../notifications'
import { useProductStore } from '../products'
import { useProjectStore } from '../projects'
import { useProjectStateStore } from '../projectStateStore'
import { useTaskStore } from '../tasks'

/** FE-9538: best-effort lifecycle-banner announce -- must never break the
 * pre-existing routing it rides alongside.
 *
 * FE-9553 added the second half. Before it, this wrote a banner row and NOTHING
 * else: an unwatched lifecycle banner expired and nothing recorded that the
 * project had ever been staged, so a lifecycle event lived on exactly one live
 * surface and zero durable ones. That already broke the rule that informational
 * lifecycle events must always reach the durable notification list, and it
 * would have made the "Lifecycle events" toggle a control that lies -- off
 * would have meant gone rather than bell-only.
 *
 * So the bell row is written UNCONDITIONALLY here, and the preference gates
 * only the banner (inside announce()). The visible consequence is a bell that
 * fills with lifecycle rows in a busy session -- and that is deliberate: it is what "the bell remembers" means, and M3's quiet
 * counter is what makes it tolerable.
 *
 * The row is keyed on RECEIPT, not on the moment name. Keying on the moment
 * would collapse a project that is activated, parked and activated again into
 * one row, silently losing a dated fact from the archive -- the same
 * distinction BELL_ROWS draws in useHubNotifications between a baton (one
 * standing obligation) and a mention (a second thing asked). The payload
 * carries no event id or timestamp, so a genuine double-delivery would produce
 * two rows; that is the safer failure, since a duplicate is noise and a dropped
 * fact is a lie.
 */
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
      // No explicit id: addNotification mints a unique one. An earlier draft
      // keyed it `lifecycle:<project>:<moment>:<now>`, which collides for two
      // events arriving in the same millisecond and silently drops the second
      // -- the very fact-loss this keying was meant to avoid. Letting the store
      // mint it removes the failure mode instead of narrowing it.
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

/**
 * Project and entity update event route definitions.
 */
export const PROJECT_EVENT_ROUTES = {
  // FE-9538: was the bare {store, action} shorthand -- converted to an
  // equivalent handler so an activation (the one 'status_changed' transition
  // this event's payload can distinguish from every other terminal/lifecycle
  // status write) additionally feeds the lifecycle banner. The
  // handleRealtimeUpdate dispatch itself is unchanged.
  project_update: {
    handler: async (payload) => {
      await useProjectStore().handleRealtimeUpdate?.(payload)
      if (payload?.update_type === 'status_changed' && payload?.status === 'active') {
        announceLifecycleMoment(payload?.project_id, 'activated')
      }
    },
  },
  'project:mission_updated': { store: 'projectState', action: 'handleMissionUpdated' },
  // Handover 0826: Server-side staging completion signal
  // D1 (Headless S3a): previously routed ONLY to projectStateStore, so the open
  // ProjectTabs flipped live but the Projects list's Staged column (ProjectsTable.vue
  // reads item.staging_status straight off the list row, not projectStateStore) stayed
  // stale until a manual refresh. Debounced so a same-tick handleStagingComplete +
  // implementation_launched pair collapses into one refetch.
  // FE-9538: additionally announces the lifecycle banner's staged moment.
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
  // CE-0029 Item 3: symmetric signal emitted by the launch_implementation endpoint.
  // FE-6174c: the mission-control roster patch was removed with Mission Control's
  // retirement; this now routes solely to projectStateStore (the solo/jobs surface
  // flips its own "Implementing" state from there).
  // D2 (Headless S3a): also debounce-refresh the Projects list for the same reason
  // as project:staging_complete above.
  // FE-9538: additionally announces the lifecycle banner's implementation-launched moment.
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
  // D14 (Headless S3a): project:launched (the near-vestigial single-project
  // POST /api/agent-jobs/launch-project endpoint) had no route at all. Mirrors
  // implementation_launched's projectState patch + debounced list refresh.
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
  // D15 (Headless S3a): projects:bulk:deactivated (product_lifecycle_service, fired
  // when activating a product auto-deactivates every active project belonging to
  // OTHER products) had no route -- the Projects list kept showing the deactivated
  // rows as active until a manual refresh. Payload only carries product_ids, so a
  // full debounced list refresh (not a per-project patch) is the correct fix.
  'projects:bulk:deactivated': {
    handler: async () => {
      useProjectStore().debouncedRefreshList?.()
    },
  },

  // Entity updates (legacy multiplexed)
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

  // Projects (MCP tool creates — frontend needs refresh)
  'project:created': {
    handler: async () => {
      const projectStore = useProjectStore()
      // refreshList() replays the active filter/sort/page. A bare fetchProjects()
      // here refetches the active-lifecycle default and, landing after the user's
      // filter fetch, clobbers it (the "Completed flashes then reverts" bug).
      await projectStore.refreshList()
    },
  },
}
