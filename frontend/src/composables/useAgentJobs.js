import { computed } from 'vue'
import api from '@/services/api'
import { useAgentJobsStore } from '@/stores/agentJobsStore'

// FE-9545: exported so JobsViewportView reuses this ONE reader instead of its own
// naive `response.data || []`, which treated the server's paginated envelope as an
// array and crashed every card render.
export function extractJobsFromResponse(responseData) {
  if (Array.isArray(responseData)) return responseData
  if (Array.isArray(responseData?.jobs)) return responseData.jobs
  if (Array.isArray(responseData?.rows)) return responseData.rows
  return []
}

export function useAgentJobs() {
  const store = useAgentJobsStore()

  const sortedJobs = computed(() => store.sortedJobs)
  const jobCount = computed(() => store.jobCount)

  async function loadJobs(projectId) {
    if (!projectId) {
      store.$reset?.()
      return []
    }

    const response = await api.agentJobs.list(projectId)
    const jobs = extractJobsFromResponse(response?.data)
    store.setJobs(jobs)
    return jobs
  }

  return {
    store,
    sortedJobs,
    jobCount,
    loadJobs,
  }
}
