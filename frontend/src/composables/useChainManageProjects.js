import { ref, computed } from 'vue'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useProjectStore } from '@/stores/projects'
import { parseErrorResponse } from '@/utils/errorMessages'

const FINISHED = new Set(['completed', 'failed', 'terminated', 'cancelled'])

function kindOf(tab) {
  if (tab.isDetached) return 'dropped'
  return FINISHED.has(tab.status) ? 'finished' : 'droppable'
}

export function useChainManageProjects({ chainCtx, started }) {
  const sequenceRunStore = useSequenceRunStore()
  const projectStore = useProjectStore()

  const open = ref(false)
  const pendingId = ref('')
  const droppingId = ref('')
  const error = ref('')

  const phase = computed(() => {
    if (started()) return 'started'
    return chainCtx.value?.locked ? 'staged' : 'editing'
  })

  const rows = computed(() =>
    (chainCtx.value?.tabs || []).map((tab) => ({
      projectId: tab.projectId,
      step: tab.order + 1,
      label: [tab.taxonomyAlias, tab.name].filter(Boolean).join(' ') || 'Project',
      kind: phase.value === 'staged' && kindOf(tab) === 'droppable' ? 'staged' : kindOf(tab),
      current: Boolean(tab.isCurrent),
    })),
  )

  function openManageProjects() {
    error.value = ''
    open.value = true
  }

  function closeManageProjects() {
    open.value = false
    pendingId.value = ''
    error.value = ''
  }

  async function performDrop(projectId) {
    const runId = chainCtx.value?.runId
    if (!runId || droppingId.value) return
    droppingId.value = projectId
    error.value = ''
    try {
      if (started()) {
        await projectStore.updateProject(projectId, { status: 'parked' })
        await sequenceRunStore.hydrate()
      } else {
        await sequenceRunStore.removeMember(runId, projectId)
      }
      pendingId.value = ''
    } catch (err) {
      pendingId.value = ''
      error.value =
        !started() && err?.response?.status === 422
          ? 'This chain has started. Close this window and try again.'
          : parseErrorResponse(err).message || 'Could not drop the project.'
    } finally {
      droppingId.value = ''
    }
  }

  function requestDrop(projectId) {
    const row = rows.value.find((r) => r.projectId === projectId)
    if (!row || row.kind !== 'droppable') return Promise.resolve()
    error.value = ''
    const remaining = rows.value.filter((r) => r.kind !== 'dropped' && r.projectId !== projectId).length
    if ((started() && row.current) || (!started() && remaining < 2)) {
      pendingId.value = projectId
      return Promise.resolve()
    }
    return performDrop(projectId)
  }

  const pendingCancelsChain = computed(() => Boolean(pendingId.value) && !started())

  function cancelDrop() {
    pendingId.value = ''
  }

  function confirmDrop() {
    return pendingId.value ? performDrop(pendingId.value) : Promise.resolve()
  }

  return {
    showManageProjects: open,
    managePhase: phase,
    manageRows: rows,
    managePendingId: pendingId,
    managePendingCancelsChain: pendingCancelsChain,
    manageDroppingId: droppingId,
    manageError: error,
    openManageProjects,
    closeManageProjects,
    requestDrop,
    cancelDrop,
    confirmDrop,
  }
}
