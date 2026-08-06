/**
 * useChainContext — FE-6174b
 *
 * The conditional multi-project layer's data source for the `/jobs` views.
 * HARVESTED from useChainCockpit (MissionControlView's data orchestration): the
 * "filter a sequence run to its <=5 projects, one active at a time" logic, lifted
 * into a new home so the `/jobs` staging + implementation variant can consume it
 * WITHOUT depending on the Mission Control surface (retired in FE-6174c).
 *
 * Reads `?run=<id>` from the route:
 *   - absent  -> `chainCtx` is null; the `/jobs` views render the BYTE-IDENTICAL
 *                solo path (the deletion test).
 *   - present -> loads the durable run record + its ordered projects and derives
 *                the tab-strip / N-M counter / conductor / per-project-status state
 *                the conditional layer needs.
 *
 * Reuse-only: consumes the existing sequenceRunStore (BE-6131a run record) +
 * api.projects + projectStateStore (live WS mission). NO new endpoint / store /
 * schema. Read-only over the run (writes flow through sequenceRunStore /
 * useChainLifecycle from the host), and it stays in sync with the store's open
 * run so WS `sequence:updated` advances the counter + tab states live.
 *
 * Edition scope: CE.
 */
import { ref, computed, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useProjectStore } from '@/stores/projects'
import { useAgentJobs } from '@/composables/useAgentJobs'
import { registerReconnectResync } from '@/stores/websocketEventRouter'

/**
 * Statuses that indicate a project's sub-orchestrator is actively running.
 * Only 'implementing' is written by the backend today; the synonyms guard against
 * a future rename without requiring a simultaneous FE change.
 */
const WORKING_STATUSES = new Set(['implementing', 'working', 'running', 'in_progress'])

export function useChainContext() {
  const route = useRoute()
  const sequenceRunStore = useSequenceRunStore()
  const projectStateStore = useProjectStateStore()
  const projectStore = useProjectStore()
  const { sortedJobs } = useAgentJobs()

  // The run currently in scope (null outside a chain). Hydrated from the store's
  // open run so WS updates flow through without a re-fetch.
  const run = ref(null)
  // Ordered project records resolved from resolved_order ({id,name,taxonomy_alias,
  // mission,product_id,_order}). Names are stable, so resolved once per load.
  const projects = ref([])

  const runId = computed(() => {
    const r = route.query?.run
    return typeof r === 'string' && r ? r : null
  })

  // Returns the number of member ids the run REFERENCED (so the caller can detect
  // an all-orphaned run). projects.value is set to the live, resolvable subset.
  async function resolveProjects(runObj) {
    const ids = runObj?.resolved_order?.length
      ? runObj.resolved_order
      : runObj?.project_ids || []
    if (!ids.length) {
      projects.value = []
      return 0
    }
    // Warm the project store (NOT a raw axios GET): this populates projectStore so
    // that switching to a sibling chain tab finds the project already resident —
    // ProjectLaunchView can then refetch quietly without the full-screen spinner
    // unmount/remount + a cold double-fetch. Per-id failures degrade gracefully:
    // a member that 404s (hard-deleted, FE-6175 RC2) is simply skipped.
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
      // FE-6175 RC2: an orphaned run whose members were ALL hard-deleted resolves
      // to zero live projects. Degrade to the byte-identical solo path instead of
      // rendering an empty chain that storms 404s for the dead members.
      if (requested > 0 && projects.value.length === 0) {
        console.warn('[useChainContext] sequence run has no resolvable members; falling back to solo', id)
        run.value = null
        projects.value = []
      }
    } catch (err) {
      // Unknown / foreign run — fall back to the solo path rather than erroring.
      console.warn('[useChainContext] could not load sequence run', err)
      run.value = null
      projects.value = []
    }
  }

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------
  const orderedIds = computed(() =>
    run.value?.resolved_order?.length ? run.value.resolved_order : run.value?.project_ids || [],
  )
  const total = computed(() => orderedIds.value.length)
  const currentIndex = computed(() =>
    typeof run.value?.current_index === 'number' ? run.value.current_index : 0,
  )
  const currentPid = computed(() => orderedIds.value[currentIndex.value] ?? null)

  // N/M counter: N = the 1-based position of the in-flight project, M = total.
  // The driver advances current_index on each completion, so N climbs 1/3 -> 2/3.
  const counter = computed(() => ({
    n: total.value ? Math.min(currentIndex.value + 1, total.value) : 0,
    m: total.value,
  }))

  // Overarching mission = the head project's mission (OD-4 — no new schema). Live
  // WS value wins over the loaded record.
  const headMission = computed(() => {
    const headId = orderedIds.value[0]
    if (!headId) return ''
    const live = projectStateStore.getProjectState(headId)
    if (live?.mission) return live.mission
    return projects.value.find((p) => p.id === headId)?.mission || ''
  })

  // FE-6199 (Unit C): the live project-less conductor agent (project_id IS NULL +
  // chain_conductor flag), for the dedicated ChainConductorCard. Null outside a chain.
  // BE-6200 (#6 follow-up): key on the FLAT `chain_conductor` field the API now
  // serializes. The old predicate (project_id IS NULL + job_metadata flag) never
  // matched: the project-scoped /jobs query excludes project_id-NULL rows, and
  // job_metadata is not serialized (and is clobbered by the WS progress handler).
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

  // Ordered tab descriptors for ProjectTabStrip (active highlighted / completed /
  // faded + the pulsing Review badge on a freshly-completed-awaiting-review tab).
  const tabs = computed(() =>
    orderedIds.value.map((pid, i) => {
      const proj = projects.value.find((p) => p.id === pid)
      const status = statusFor(pid)
      const isCompleted = status === 'completed'
      const isWorking = WORKING_STATUSES.has(status)
      // isPlanning (FE-9239): the member is actively being staged, so the tab strip
      // can show PLANNING instead of a generic WAITING. Prefer the live WS-updated
      // projectStateStore flags (isStaging/isStaged) — they react instantly to
      // staging events without waiting for a project refetch — and fall back to the
      // resolved project record's staging_status only when no live state exists yet.
      // 'staging_complete' (mission written, Implement lit, no workers yet) is
      // deliberately NOT planning by default — it renders WAITING pending design
      // review (see ProjectTabStrip.vue badgeState for the one-line change spot).
      const liveState = projectStateStore.getProjectState(pid)
      const stagingActive = liveState
        ? Boolean(liveState.isStaging || liveState.isStaged)
        : proj?.staging_status === 'staging' || proj?.staging_status === 'staged'
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
        // needsReview: completed by the conductor AND not yet reviewed client-side.
        // 'awaiting_review' is a dead state (no BE code ever writes it) — ignore it.
        needsReview: isCompleted && !sequenceRunStore.isReviewed(run.value?.id, pid),
        isStarted: status !== '' && status !== 'pending',
        isWorking,
        isPlanning: stagingActive && !isCompleted && !isWorking,
      }
    }),
  )

  // The single bundle handed to the /jobs views. NULL outside a chain -> solo path.
  const chainCtx = computed(() => {
    if (!run.value) return null
    return {
      run: run.value,
      runId: run.value.id,
      tabs: tabs.value,
      counter: counter.value,
      currentPid: currentPid.value,
      headMission: headMission.value,
      chainMission: run.value?.chain_mission ?? '',  // FE-6199 B2: canonical field from run
      conductor: conductor.value,
      conductorAgent: conductorAgent.value,
      locked: run.value.locked === true,
    }
  })

  // Stay in sync with the store's open run so WS `sequence:updated` (which the
  // store re-hydrates) advances counter/tab states without us re-fetching.
  watch(
    () => sequenceRunStore.activeRun,
    (ar) => {
      if (ar && runId.value && ar.id === runId.value) run.value = ar
    },
  )

  const unregisterResync = registerReconnectResync(() => loadRun(runId.value))
  watch(runId, (id) => loadRun(id), { immediate: true })
  onUnmounted(() => unregisterResync())

  return { chainCtx, run, projects, loadRun }
}
