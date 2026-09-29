import { ref, computed, watch } from 'vue'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useProjectStore } from '@/stores/projects'

const WORKING_STATUSES = new Set(['implementing', 'working', 'running', 'in_progress'])

const PLANNING_STATUSES = new Set(['planning'])

const GOAL_HEADING = /^#+\s*(?:chain mission:\s*)?(.+?)\s*$/i

function orderOf(run) {
  return run?.resolved_order?.length ? run.resolved_order : run?.project_ids || []
}

function chainDisplayName(run, members = []) {
  const firstLine = String(run?.chain_mission || '').trim().split('\n')[0] || ''
  const heading = firstLine.match(GOAL_HEADING)
  if (heading) return heading[1]
  const labels = orderOf(run)
    .map((pid) => {
      const member = members.find((m) => m.id === pid)
      return member?.taxonomy_alias || member?.name || ''
    })
    .filter(Boolean)
  return labels.length ? labels.join(' → ') : 'Chain'
}

export function useChainContext({ runId = () => null, projectId = () => null } = {}) {
  const sequenceRunStore = useSequenceRunStore()
  const projectStore = useProjectStore()

  function findRun() {
    const pools = [sequenceRunStore.runsById, sequenceRunStore.reviewPendingById]
    const wantedRun = runId()
    if (wantedRun) {
      for (const pool of pools) {
        if (pool.has(wantedRun)) return pool.get(wantedRun)
      }
      return null
    }
    const pid = projectId()
    if (!pid) return null
    for (const pool of pools) {
      for (const run of pool.values()) {
        if (orderOf(run).includes(pid) || run.project_ids?.includes(pid)) return run
      }
    }
    return null
  }

  const run = computed(findRun)
  const orderedIds = computed(() => orderOf(run.value))

  function needsDetail(id) {
    const known = projectStore.projectById(id)
    return !known || known.description === undefined
  }
  const loadedIds = ref([])
  async function resolveProjects(ids) {
    if (!ids.length) return
    await Promise.allSettled(ids.filter(needsDetail).map((id) => projectStore.fetchProject(id)))
    loadedIds.value = ids
  }
  watch(
    () => orderedIds.value.join(','),
    () => resolveProjects(orderedIds.value),
    { immediate: true },
  )

  const projects = computed(() =>
    loadedIds.value
      .map((id, i) => {
        const p = projectStore.projectById(id)
        return p ? { ...p, _order: i } : null
      })
      .filter(Boolean),
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
      name: chainDisplayName(run.value, projects.value),
      tabs: tabs.value,
      projects: projects.value,
      counter: counter.value,
      currentPid: currentPid.value,
      chainMission: run.value?.chain_mission ?? '',
      conductor: conductor.value,
      locked: run.value.locked === true,
    }
  })

  return { chainCtx, run, projects }
}
