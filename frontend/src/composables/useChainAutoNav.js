import { watch } from 'vue'
import { useProjectStateStore } from '@/stores/projectStateStore'

export const USER_ACTION_GUARD_MS = 4000

export function useChainAutoNav({ chainCtx, projectId, activeTab, router, route, now = () => Date.now() }) {
  const projectStateStore = useProjectStateStore()

  let suppressUntil = 0

  function markUserAction() {
    suppressUntil = now() + USER_ACTION_GUARD_MS
  }

  function suppressed() {
    return now() < suppressUntil
  }

  function chainBlocked() {
    return !chainCtx?.value || suppressed()
  }

  watch(
    () => projectStateStore.getProjectState(projectId.value)?.stagingComplete === true,
    (isComplete, was) => {
      if (!isComplete || was) return
      if (suppressed()) return
      activeTab.value = 'launch'
    },
  )

  watch(
    () => projectStateStore.getProjectState(projectId.value)?.implementationLaunched === true,
    (launched, was) => {
      if (!launched || was) return
      const source = projectStateStore.getProjectState(projectId.value)?.lastLaunchSource || null
      if (source === 'mcp') {
        activeTab.value = 'jobs'
        return
      }
      if (suppressed()) return
      activeTab.value = 'jobs'
    },
  )

  watch(
    () => chainCtx?.value?.currentPid || null,
    (pid, prev) => {
      if (!pid || !prev || pid === prev) return
      if (chainBlocked()) return
      if (pid === projectId.value) {
        activeTab.value = 'jobs'
        return
      }
      if (!route.query?.run) return
      router.replace({
        name: 'ProjectLaunch',
        params: { projectId: pid },
        query: { ...route.query, tab: 'jobs' },
      })
    },
  )

  return { markUserAction }
}
