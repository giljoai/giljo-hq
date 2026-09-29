
import { computed, getCurrentInstance, onUnmounted, reactive, ref, watch } from 'vue'
import { useWebSocketStore } from '@/stores/websocket'
import { useProjectCloseout } from '@/composables/useProjectCloseout'
import { isAwaitingUser } from '@/utils/statusConfig'
import { isOrchestrator } from '@/utils/agentDisplay'

export function useBoardCloseout({ agentsFor, refresh }) {
  const focusProject = ref(null)
  const focusProjectId = computed(() => focusProject.value?.id || null)
  const focusAgents = computed(() => (focusProjectId.value ? agentsFor(focusProjectId.value) : []))

  const closeout = useProjectCloseout({
    project: focusProject,
    projectId: focusProjectId,
    sortedJobs: focusAgents,
    onComplete: () => refresh?.(),
  })

  const showDecisionModal = ref(false)
  const showOrchUnlockedBanner = ref(false)

  const orchestratorJob = computed(() => focusAgents.value.find(isOrchestrator) || null)
  const orchestratorJobId = computed(() => orchestratorJob.value?.job_id || orchestratorJob.value?.id || null)
  const orchestratorCloseoutBlocked = computed(() =>
    orchestratorJob.value ? isAwaitingUser(orchestratorJob.value.status) : false,
  )

  function focus(project) {
    if (project && project.id !== focusProject.value?.id) {
      const previous = focusProjectId.value
      focusProject.value = project
      if (previous) closeout.reset?.(project.id, previous)
    } else if (project) {
      focusProject.value = project
    }
  }

  function openReview(project) {
    focus(project)
    closeout.openCloseoutModal()
  }

  function openDecision(project) {
    focus(project)
    showDecisionModal.value = true
  }

  function onApprovalDecided() {
    showDecisionModal.value = false
    showOrchUnlockedBanner.value = true
  }

  watch([closeout.allJobsTerminal, closeout.projectDoneStatus], ([terminal, done]) => {
    if (terminal || done) showOrchUnlockedBanner.value = false
  })
  const orchMessagesWaiting = computed(() => orchestratorJob.value?.messages_waiting_count ?? 0)
  watch(orchMessagesWaiting, (count, previous) => {
    if (showOrchUnlockedBanner.value && previous > 0 && count === 0) showOrchUnlockedBanner.value = false
  })

  const wsStore = useWebSocketStore()
  let offMemory = null
  try {
    offMemory = wsStore.on('product:memory:updated', (payload) => {
      const entryProjectId = payload?.entry?.project_id
      if (entryProjectId && entryProjectId === focusProjectId.value) closeout.memoryWritten.value = true
    })
  } catch {
    offMemory = null
  }
  if (getCurrentInstance()) {
    onUnmounted(() => {
      offMemory?.()
      closeout.cleanup?.()
    })
  }

  const banner = computed(() => {
    if (!focusProject.value) return null
    return {
      projectDoneStatus: closeout.projectDoneStatus.value,
      orchestratorCloseoutBlocked: orchestratorCloseoutBlocked.value,
      showOrchUnlockedBanner: showOrchUnlockedBanner.value,
      showCloseoutButton: closeout.showCloseoutButton.value,
      showMemoryPending: closeout.showMemoryPending.value,
      allJobsTerminal: closeout.allJobsTerminal.value,
      memoryPollTimedOut: closeout.memoryPollTimedOut.value,
      memoryPollError: closeout.memoryPollError.value,
      closingWithoutSummary: closeout.closingWithoutSummary.value,
    }
  })

  function consumeArrival(query, project, { onDetail } = {}) {
    const rest = { ...query }
    let consumed = false
    if (project && query.detail === '1') {
      onDetail?.(project)
      delete rest.detail
      consumed = true
    }
    if (project && query.review === '1') {
      openReview(project)
      delete rest.review
      consumed = true
    }
    if (project && query.decide === '1') {
      openDecision(project)
      delete rest.decide
      consumed = true
    }
    if (rest.tab) {
      delete rest.tab
      consumed = true
    }
    return consumed ? rest : null
  }

  return reactive({
    focusProject,
    focusAgents,
    focus,
    openReview,
    openDecision,
    onApprovalDecided,
    showDecisionModal,
    showOrchUnlockedBanner,
    orchestratorJobId,
    orchestratorCloseoutBlocked,
    banner,
    consumeArrival,
    ...closeout,
  })
}
