import { ref, computed, watch } from 'vue'
import api from '@/services/api'
import { useNotificationStore } from '@/stores/notifications'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useProjectCloseout({ project, projectId, sortedJobs, onComplete }) {
  const notificationStore = useNotificationStore()
  const { showToast } = useToast()

  const showCloseoutModal = ref(false)
  const memoryWritten = ref(false)
  const memoryPollTimedOut = ref(false)
  const memoryPollError = ref(false)

  const MEMORY_POLL_TIMEOUT_MS = 30_000

  let memoryCheckTimeout = null

  const projectDoneStatus = computed(() => {
    const status = project.value?.status
    if (['completed', 'terminated', 'cancelled'].includes(status)) return status
    return null
  })

  const allJobsTerminal = computed(() => {
    if (['completed', 'terminated', 'cancelled'].includes(project.value?.status)) return false
    if (
      project.value?.staging_status === 'staging_complete'
      && !project.value?.implementation_launched_at
    ) {
      return false
    }
    const jobs = sortedJobs.value || []
    if (!jobs.length) return false
    const isTerminal = (status) =>
      status === 'complete' || status === 'completed' || status === 'decommissioned' || status === 'closed'
    const allTerminal = jobs.every((job) => isTerminal(job.status))
    if (!allTerminal) return false
    const orchestrator = jobs.find((job) => job.agent_display_name === 'orchestrator')
    return Boolean(orchestrator && isTerminal(orchestrator.status))
  })

  const showCloseoutButton = computed(() => {
    if (!allJobsTerminal.value) return false
    if (!project.value?.product_id) return true
    return memoryWritten.value
  })

  const showMemoryPending = computed(() => {
    if (!allJobsTerminal.value) return false
    if (!project.value?.product_id) return false
    if (memoryPollTimedOut.value || memoryPollError.value) return false
    return !memoryWritten.value
  })

  function openCloseoutModal() {
    showCloseoutModal.value = true
  }

  async function handleCloseoutComplete() {
    showCloseoutModal.value = false
    notificationStore.clearForProject(projectId.value)
    showToast({ message: 'Project closed out successfully', type: 'success' })
    onComplete?.()
  }

  function startMemoryPoll() {
    clearTimeout(memoryCheckTimeout)
    memoryPollTimedOut.value = false
    memoryPollError.value = false

    const productId = project.value?.product_id
    if (!productId) return

    async function checkMemory() {
      try {
        const res = await api.products.getMemoryEntries(productId, {
          project_id: projectId.value,
          limit: 1,
        })
        if (res.data?.entries?.length > 0) {
          memoryWritten.value = true
          memoryPollTimedOut.value = false
          memoryPollError.value = false
          return true
        }
      } catch {
        memoryPollError.value = true
        return true
      }
      return false
    }

    checkMemory().then((done) => {
      if (done) return
      memoryCheckTimeout = setTimeout(() => {
        if (!memoryWritten.value) {
          memoryPollTimedOut.value = true
        }
      }, MEMORY_POLL_TIMEOUT_MS)
    })
  }

  watch(
    allJobsTerminal,
    (terminal) => {
      clearTimeout(memoryCheckTimeout)
      if (!terminal || memoryWritten.value) return
      startMemoryPoll()
    },
    { immediate: true },
  )

  function retryMemoryPoll() {
    startMemoryPoll()
  }

  const DEFAULT_CLOSE_REASON = 'Closed from the dashboard: the agents stopped without writing a closeout.'
  const closingWithoutSummary = ref(false)

  async function closeWithoutSummary(reason) {
    if (closingWithoutSummary.value) return false
    closingWithoutSummary.value = true
    try {
      await api.projects.closeoutWithoutSummary(projectId.value, (reason || '').trim() || DEFAULT_CLOSE_REASON)
      startMemoryPoll()
      return true
    } catch (error) {
      showToast({
        message: parseErrorResponse(error).message || 'Could not close the project. Try again.',
        type: 'error',
      })
      return false
    } finally {
      closingWithoutSummary.value = false
    }
  }

  function reset(newProjectId, oldProjectId) {
    if (oldProjectId && oldProjectId !== newProjectId) {
      clearTimeout(memoryCheckTimeout)
      memoryWritten.value = false
      memoryPollTimedOut.value = false
      memoryPollError.value = false
    }
  }

  function cleanup() {
    clearTimeout(memoryCheckTimeout)
  }

  return {
    showCloseoutModal,
    memoryWritten,
    memoryPollTimedOut,
    memoryPollError,
    projectDoneStatus,
    allJobsTerminal,
    showCloseoutButton,
    showMemoryPending,
    openCloseoutModal,
    handleCloseoutComplete,
    retryMemoryPoll,
    closeWithoutSummary,
    closingWithoutSummary,
    reset,
    cleanup,
  }
}
