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


  async function loadProjectData(pid, { fetchProject = false } = {}) {
    if (!pid) return

    tabsStore.currentProject = getProject()
    projectStateStore.setProject(getProject())

    if (fetchProject) {
      await projectStore.fetchProject(pid)
    }

    try {
      await loadJobs(pid)
    } catch (error) {
      console.warn('[ProjectTabs] Failed to load project data:', error)
    }
  }

  async function refetchProject(pid) {
    if (!pid) return
    await projectStore.fetchProject(pid)
  }


  watch(
    () => getProject()?.execution_mode,
    (newMode) => {
      executionMode.value = newMode || null
      if (newMode && (missionText.value || isProjectStaged.value || isProjectStaging.value)) {
        executionPlatform.value = newMode
      }
    },
    { immediate: true },
  )


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
      await loadProjectData(pid, { fetchProject: Boolean(oldPid) })
    },
    { immediate: true },
  )

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


  let unregisterReconnectResync = null
  let unsubscribeMemory = null
  let unsubscribeStagingComplete = null
  let unsubscribeImplLaunched = null

  onMounted(() => {
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
