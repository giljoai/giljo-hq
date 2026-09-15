import { ref, computed, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useNotificationStore } from '@/stores/notifications'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useProjectStore } from '@/stores/projects'
import { useAgentJobs } from '@/composables/useAgentJobs'
import { registerReconnectResync } from '@/stores/websocketEventRouter'

const WORKING_STATUSES = new Set(['implementing', 'working', 'running', 'in_progress'])

const PLANNING_STATUSES = new Set(['planning'])

export function useChainContext() {
  const route = useRoute()
  const sequenceRunStore = useSequenceRunStore()
  const projectStateStore = useProjectStateStore()
  const projectStore = useProjectStore()
  const { sortedJobs } = useAgentJobs()

  const run = ref(null)
  const projects = ref([])

  const runId = computed(() => {
    const r = route.query?.run
    return typeof r === 'string' && r ? r : null
  })

  async function resolveProjects(runObj) {
    const ids = runObj?.resolved_order?.length
      ? runObj.resolved_order
      : runObj?.project_ids || []
    if (!ids.length) {
      projects.value = []
      return 0
    }
    const settled = await Promise.allSettled(ids.map((id) => projectStore.fetchProject(id)))
    projects.value = ids
      .map((id, i) => {
        if (settled[i].status !== 'fulfilled') return null
        const p = projectStore.projectById(id)
        return p ? { ...p, _order: i } : null
      })
      .filter(Boolean)
    return ids.length
  }

  async function loadRun(id) {
    if (!id) {
      run.value = null
      projects.value = []
      return
    }
    try {
      const fetched = await sequenceRunStore.fetchRun(id)
      run.value = fetched
      const requested = await resolveProjects(fetched)
      if (requested > 0 && projects.value.length === 0) {
        console.warn('[useChainContext] sequence run has no resolvable members; falling back to solo', id)
        run.value = null
        projects.value = []
      }
    } catch (err) {
      console.warn('[useChainContext] could not load sequence run', err)
      run.value = null
      projects.value = []
    }
  }

  const orderedIds = computed(() =>
    run.value?.resolved_order?.length ? run.value.resolved_order : run.value?.project_ids || [],
  )
  const total = computed(() => orderedIds.value.length)
  const currentIndex = computed(() =>
    typeof run.value?.current_index === 'number' ? run.value.current_index : 0,
  )
  const currentPid = computed(() => orderedIds.value[currentIndex.value] ?? null)

  const counter = computed(() => ({
    n: total.value ? Math.min(currentIndex.value + 1, total.value) : 0,
    m: total.value,
  }))

  const headMission = computed(() => {
    const headId = orderedIds.value[0]
    if (!headId) return ''
    const live = projectStateStore.getProjectState(headId)
    if (live?.mission) return live.mission
    return projects.value.find((p) => p.id === headId)?.mission || ''
  })

  const conductorAgent = computed(
    () => (sortedJobs.value || []).find((j) => j.chain_conductor === true) || null,
  )

  const conductor = computed(() => ({
    agentId: run.value?.conductor_agent_id || '',
    projectId: run.value?.conductor_project_id || '',
    label: run.value?.conductor_label || 'Conductor (orchestrator A)',
  }))

  function statusFor(pid) {
    return run.value?.project_statuses?.[pid] || ''
  }

  const tabs = computed(() =>
    orderedIds.value.map((pid, i) => {
      const proj = projects.value.find((p) => p.id === pid)
      const status = statusFor(pid)
      const isCompleted = status === 'completed'
      const isWorking = WORKING_STATUSES.has(status)
      const isPlanning = PLANNING_STATUSES.has(status) && !isCompleted && !isWorking
      return {
        projectId: pid,
        order: i,
        name: proj?.name || '',
        taxonomyAlias: proj?.taxonomy_alias || '',
        taxonomy: proj?.project_type || null,
        productId: proj?.product_id || '',
        status,
        isCurrent: pid === currentPid.value,
        isCompleted,
        needsReview: isCompleted && !sequenceRunStore.isReviewed(run.value?.id, pid),
        isStarted: status !== '' && status !== 'pending',
        isWorking,
        isPlanning,
      }
    }),
  )

  const chainCtx = computed(() => {
    if (!run.value) return null
    return {
      run: run.value,
      runId: run.value.id,
      tabs: tabs.value,
      counter: counter.value,
      currentPid: currentPid.value,
      headMission: headMission.value,
      chainMission: run.value?.chain_mission ?? '',
      conductor: conductor.value,
      conductorAgent: conductorAgent.value,
      locked: run.value.locked === true,
    }
  })

  watch(
    () => sequenceRunStore.activeRun,
    (ar) => {
      if (ar && runId.value && ar.id === runId.value) run.value = ar
    },
  )

  watch(
    () => sequenceRunStore.retiredRunNotice,
    (notice) => {
      if (!notice || notice.runId !== run.value?.id) return
      run.value = null
      projects.value = []
      useNotificationStore().addNotification({
        id: `chain-retired:${notice.runId}`,
        type: 'lifecycle',
        severity: 'info',
        title: 'Chain finished',
        message: 'This chain has finished; its record was retired.',
      })
      sequenceRunStore.clearRetiredRunNotice()
    },
  )

  const unregisterResync = registerReconnectResync(() => loadRun(runId.value))
  watch(runId, (id) => loadRun(id), { immediate: true })
  onUnmounted(() => unregisterResync())

  return { chainCtx, run, projects, loadRun }
}
