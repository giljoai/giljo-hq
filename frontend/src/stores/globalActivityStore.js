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

  function recordActivity(projectId) {
    if (!projectId) return
    const next = new Map(countsByProject.value)
    next.set(projectId, (next.get(projectId) ?? 0) + 1)
    countsByProject.value = next
  }

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
