/**
 * globalActivityStore.js — FE-9501b (D5)
 *
 * The activity surface for a project you do NOT currently have open.
 * websocketEventRouter's PROJECT_SCOPED_EVENTS filter (Handover 0463) drops
 * agent:created/status_changed/removed and job:progress_update for any
 * project that isn't the open tab -- correct for agentJobsStore (dropping
 * there prevents a ghost row for a project this client never fetched), but
 * it also means an agent working on an unopened project is invisible
 * everywhere else in the app. That guard is NOT relaxed here.
 *
 * This store is fed by a SEPARATE, additive routing pass
 * (routeGlobalActivityEvent in websocketEventRouter.js) that is NOT subject
 * to the project-scope filter -- only the tenant check. It is deliberately
 * dumb: COUNT, do not hydrate. No fetch, no row shape, just an integer per
 * project_id. The consuming UI (NavigationDrawer's Projects badge) decides
 * what to show; a click navigates, nothing here ever does.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const useGlobalActivityStore = defineStore('globalActivity', () => {
  const countsByProject = ref(new Map())

  const totalCount = computed(() => {
    let sum = 0
    for (const n of countsByProject.value.values()) sum += n
    return sum
  })

  const activeProjectIds = computed(() => Array.from(countsByProject.value.keys()))

  function getCount(projectId) {
    if (!projectId) return 0
    return countsByProject.value.get(projectId) ?? 0
  }

  /** Record one unit of activity for a project. Cheap: a Map write, never a fetch. */
  function recordActivity(projectId) {
    if (!projectId) return
    const next = new Map(countsByProject.value)
    next.set(projectId, (next.get(projectId) ?? 0) + 1)
    countsByProject.value = next
  }

  /** Clear the count for a project -- called when the user actually opens it. */
  function clearActivity(projectId) {
    if (!projectId || !countsByProject.value.has(projectId)) return
    const next = new Map(countsByProject.value)
    next.delete(projectId)
    countsByProject.value = next
  }

  function $reset() {
    countsByProject.value = new Map()
  }

  return {
    countsByProject,
    totalCount,
    activeProjectIds,
    getCount,
    recordActivity,
    clearActivity,
    $reset,
  }
})
