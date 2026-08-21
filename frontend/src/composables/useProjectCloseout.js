import { ref, computed, watch } from 'vue'
import api from '@/services/api'
import { useNotificationStore } from '@/stores/notifications'
import { useToast } from '@/composables/useToast'

/**
 * Manages the project closeout gate: detects when all agent jobs reach terminal
 * state, polls for 360 memory writes, and exposes the modal + guidance flags.
 *
 * @param {object} options
 * @param {import('vue').Ref}       options.project     - Reactive project object ref
 * @param {import('vue').ComputedRef} options.projectId  - Computed project ID string
 * @param {import('vue').ComputedRef} options.sortedJobs - Computed array of agent jobs
 * @param {Function} [options.onComplete]               - Called after closeout or continue
 * @returns Reactive state, computeds, and action methods
 */
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
    // CE-0029 Item 1: project is now a reactive parent-owned ref that
    // refetches on project:staging_complete + project:implementation_launched
    // WS events. Both staging_status and implementation_launched_at update
    // in place — no dual-source store-OR-prop fallback needed (the CE-0028b
    // band-aid that this refactor retires).
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
    // TEMP 2026-05-15: suppressed timeout/error UI so spinner stays visible until memory lands.
    // Product decision: infinite spinner is preferred over the "Closeout may have failed" warning, since memory
    // always arrives in practice. Revisit ~2026-05-29 — either restore this line or delete it.
    // if (memoryPollTimedOut.value || memoryPollError.value) return false
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

    // Check immediately
    checkMemory().then((done) => {
      if (done) return
      // Start 30s timeout
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

  function dismissMemoryPollError() {
    memoryPollTimedOut.value = false
    memoryPollError.value = false
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
    dismissMemoryPollError,
    reset,
    cleanup,
  }
}
