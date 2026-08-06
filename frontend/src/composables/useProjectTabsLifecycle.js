/**
 * useProjectTabsLifecycle.js — FE-6042c
 *
 * Extracted from ProjectTabs.vue: WS-subscription lifecycle, project data-load,
 * and refetch-on-WS-event logic. Contains all onMounted/onBeforeUnmount hooks
 * and the watches that drive data loading when projectId changes.
 *
 * Container (ProjectTabs.vue) keeps template, style, and presentation computeds.
 * Edition scope: CE
 *
 * @param {Object} ctx
 * @param {import('vue').ComputedRef<string|null>} ctx.projectId
 * @param {import('vue').Ref<string>} ctx.executionMode    from useExecutionMode
 * @param {import('vue').Ref<string|null>} ctx.executionPlatform from useExecutionMode
 * @param {import('vue').ComputedRef<string>} ctx.missionText
 * @param {import('vue').ComputedRef<boolean>} ctx.isProjectStaged
 * @param {import('vue').ComputedRef<boolean>} ctx.isProjectStaging
 * @param {import('vue').Ref<boolean>} ctx.memoryWritten   from useProjectCloseout
 * @param {Function} ctx.resetCloseout                     from useProjectCloseout
 * @param {Function} ctx.cleanupCloseout                   from useProjectCloseout
 * @param {Function} ctx.getProject                        getter returning props.project (reactive)
 */
import { watch, onMounted, onBeforeUnmount } from 'vue'
import { useWebSocketStore } from '@/stores/websocket'
import { useProjectStore } from '@/stores/projects'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useProjectTabsStore } from '@/stores/projectTabs'
import { useAgentJobs } from '@/composables/useAgentJobs'
import { registerReconnectResync } from '@/stores/websocketEventRouter'
import { PRODUCT_NAME } from '@/branding'

export function useProjectTabsLifecycle({
  projectId,
  executionMode,
  executionPlatform,
  missionText,
  isProjectStaged,
  isProjectStaging,
  memoryWritten,
  resetCloseout,
  cleanupCloseout,
  getProject,
}) {
  const wsStore = useWebSocketStore()
  const projectStore = useProjectStore()
  const projectStateStore = useProjectStateStore()
  const tabsStore = useProjectTabsStore()
  const { loadJobs } = useAgentJobs()

  // ---------------------------------------------------------------------------
  // Data-load helpers
  // ---------------------------------------------------------------------------

  async function loadProjectData(pid, { fetchProject = false } = {}) {
    if (!pid) return

    // Seed the nav pointer + derived-state store from the entity the project
    // store already owns (complete normalize, not a whitelist patch).
    tabsStore.currentProject = getProject()
    projectStateStore.setProject(getProject())

    if (fetchProject) {
      // FE-3007a: re-pull through the store (single owner). Used on a real
      // project switch and on WS reconnect — NOT on the initial mount, where
      // the view's single fetch already populated the store (no double-fetch).
      // FE-9122: projects.js's _upsertEntity bridge hydrates projectStateStore
      // from this fetch automatically — no manual setProject needed here.
      await projectStore.fetchProject(pid)
    }

    try {
      // BE-9012d: the `loadMessages().length > 0 -> setStagingComplete` fallback
      // was removed with the retired bus (`useProjectMessages`/`/api/v1/messages`).
      // It was already redundant: setProject() above derives stagingComplete
      // directly from the authoritative project.staging_status field (with a
      // monotonic OR-merge, so this ordering change cannot regress the flag).
      await loadJobs(pid)
    } catch (error) {
      console.warn('[ProjectTabs] Failed to load project data:', error)
    }
  }

  /**
   * FE-3007a: full-refetch-on-event into the store (generalized from the old
   * CE-0029 refetchLocalProject). The store is the single owner; the view's
   * store-backed computed updates reactively — no local copy to patch.
   */
  async function refetchProject(pid) {
    if (!pid) return
    // FE-9122: projects.js's _upsertEntity bridge hydrates projectStateStore
    // from this fetch automatically — no manual setProject needed.
    await projectStore.fetchProject(pid)
  }

  // ---------------------------------------------------------------------------
  // Watches
  // ---------------------------------------------------------------------------

  watch(
    () => getProject()?.execution_mode,
    (newMode) => {
      // NULL-state redesign: preserve null when the project has no chosen mode
      // (do not pin to 'multi_terminal'), so the staging request omits the mode
      // and the backend gate can fire. The radio sync below is already null-safe.
      executionMode.value = newMode || null
      if (newMode && (missionText.value || isProjectStaged.value || isProjectStaging.value)) {
        executionPlatform.value = newMode
      }
    },
    { immediate: true },
  )

  // FE-6019 is now covered by the getProject().execution_mode watch above:
  // WS events refetch into the store, props.project (the store entity) changes,
  // and that watch re-syncs executionMode — no separate localProject watch.

  // Sync radio selection once mission is loaded or staged state hydrated
  watch(
    [missionText, isProjectStaged],
    ([newMission, staged]) => {
      if ((newMission || staged) && executionPlatform.value === null) {
        const mode = getProject()?.execution_mode
        if (mode) {
          executionPlatform.value = mode
        }
      }
    },
  )

  watch(
    projectId,
    async (pid, oldPid) => {
      if (oldPid) {
        wsStore.unsubscribe('project', oldPid)
      }

      if (!pid) return

      if (oldPid && oldPid !== pid) {
        tabsStore.isLaunched = false
        projectStateStore.setLaunched(pid, false)
        resetCloseout(pid, oldPid)
      }

      wsStore.subscribeToProject(pid)
      // FE-3007a: refetch only on a real project SWITCH. On the initial mount
      // (oldPid undefined) the view already fetched the project into the store,
      // so we skip the refetch here — killing the page-open double-fetch.
      await loadProjectData(pid, { fetchProject: Boolean(oldPid) })
    },
    { immediate: true },
  )

  // Handover 0440c: Update browser tab title when project loads
  watch(
    getProject,
    (proj) => {
      if (proj) {
        const prefix = proj.taxonomy_alias && proj.series_number ? `${proj.taxonomy_alias} ` : ''
        document.title = `${prefix}${proj.name} - GiljoAI`
      }
    },
    { immediate: true },
  )

  // ---------------------------------------------------------------------------
  // Mount / Unmount lifecycle
  // ---------------------------------------------------------------------------

  let unregisterReconnectResync = null
  let unsubscribeMemory = null
  let unsubscribeStagingComplete = null
  let unsubscribeImplLaunched = null

  onMounted(() => {
    // FE-3007b: register the OPEN-project resync into the generalized
    // reconnect-resync registry instead of owning a private onConnectionChange
    // listener. On any reconnect (automatic OR manual) the open project's
    // entity, messages and agent jobs refetch via loadProjectData.
    unregisterReconnectResync = registerReconnectResync(() =>
      loadProjectData(projectId.value, { fetchProject: true }),
    )

    try {
      unsubscribeMemory = wsStore.on('product:memory:updated', (payload) => {
        const entryProjectId = payload?.entry?.project_id
        if (entryProjectId === projectId.value) {
          memoryWritten.value = true
        }
      })
    } catch {
      console.warn('[ProjectTabs] Failed to subscribe to memory events')
    }

    try {
      unsubscribeStagingComplete = wsStore.on('project:staging_complete', (payload) => {
        if (payload?.project_id && payload.project_id === projectId.value) {
          refetchProject(projectId.value)
        }
      })
    } catch {
      console.warn('[ProjectTabs] Failed to subscribe to project:staging_complete')
    }

    try {
      unsubscribeImplLaunched = wsStore.on('project:implementation_launched', (payload) => {
        if (payload?.project_id && payload.project_id === projectId.value) {
          refetchProject(projectId.value)
        }
      })
    } catch {
      console.warn('[ProjectTabs] Failed to subscribe to project:implementation_launched')
    }
  })

  onBeforeUnmount(() => {
    if (projectId.value) {
      wsStore.unsubscribe('project', projectId.value)
    }
    unregisterReconnectResync?.()
    unsubscribeMemory?.()
    unsubscribeStagingComplete?.()
    unsubscribeImplLaunched?.()
    cleanupCloseout()
    document.title = PRODUCT_NAME
  })

  return {
    loadProjectData,
    refetchProject,
  }
}
