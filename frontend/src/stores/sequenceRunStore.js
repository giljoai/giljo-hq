import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { immutableMapSet, immutableMapDelete } from './immutableHelpers'
import { useProductStore } from '@/stores/products'
import { useNotificationStore } from '@/stores/notifications'
import api from '@/services/api'

const ACTIVE_RUN_STATUSES = ['pending', 'running', 'stalled']
const CHAIN_FINISHED_STATUSES = new Set(['completed', 'failed', 'terminated', 'cancelled'])
const CHAIN_UNSTARTED_MEMBER_STATUSES = new Set(['', 'pending', 'staged'])
const CHAIN_RUNNING_STATUSES = new Set(['running', 'stalled'])

function normalizeRun(raw) {
  if (!raw) return null
  const id = raw.id || raw.run_id
  if (!id) return null
  return {
    id,
    tenant_key: raw.tenant_key ?? null,
    project_ids: Array.isArray(raw.project_ids) ? raw.project_ids : [],
    resolved_order: Array.isArray(raw.resolved_order) ? raw.resolved_order : [],
    current_index: typeof raw.current_index === 'number' ? raw.current_index : 0,
    execution_mode: raw.execution_mode ?? null,
    status: raw.status ?? null,
    review_policy: raw.review_policy ?? null,
    project_statuses:
      raw.project_statuses && typeof raw.project_statuses === 'object' ? raw.project_statuses : {},
    conductor_agent_id: raw.conductor_agent_id ?? null,
    conductor_project_id: raw.conductor_project_id ?? null,
    conductor_label: raw.conductor_label ?? null,
    created_at: raw.created_at ?? null,
    updated_at: raw.updated_at ?? null,
    locked: typeof raw.locked === 'boolean' ? raw.locked : false,
    chain_mission: typeof raw.chain_mission === 'string' ? raw.chain_mission : (raw.chain_mission ?? null),
    reviewed_project_ids: Array.isArray(raw.reviewed_project_ids) ? raw.reviewed_project_ids : [],
  }
}

export const useSequenceRunStore = defineStore('sequenceRun', () => {
  const runsById = ref(new Map())
  const activeRun = ref(null)
  const reviewedProjects = ref(new Map())
  const reviewPendingById = ref(new Map())
  const loading = ref(false)
  const error = ref(null)
  const retiredRunNotice = ref(null)
  const scopedProductId = ref(null)


  const activeRuns = computed(() => Array.from(runsById.value.values()))

  const activeChainProjectIds = computed(() => {
    const ids = new Set()
    for (const run of runsById.value.values()) {
      for (const pid of run.project_ids) ids.add(pid)
    }
    return Array.from(ids)
  })

  function isProjectInActiveChain(projectId) {
    if (!projectId) return false
    for (const run of runsById.value.values()) {
      if (run.project_ids.includes(projectId)) return true
    }
    return false
  }

  function runForProject(projectId) {
    if (!projectId) return null
    for (const run of runsById.value.values()) {
      if (run.project_ids.includes(projectId)) return run
    }
    return null
  }

  function projectChainStatus(projectId) {
    const run = runForProject(projectId)
    return run ? run.project_statuses?.[projectId] ?? null : null
  }

  function isProjectStartable(projectId) {
    if (!projectId) return false
    const run = runForProject(projectId)
    if (!run) return false
    const order = run.resolved_order?.length ? run.resolved_order : run.project_ids || []
    const index = order.indexOf(projectId)
    if (index < 0) return false
    if (CHAIN_FINISHED_STATUSES.has(run.project_statuses?.[projectId])) return false
    if (index <= (run.current_index ?? 0)) return true
    return run.project_statuses?.[order[index - 1]] === 'completed'
  }

  function isProjectRunLocked(projectId) {
    const run = runForProject(projectId)
    return run ? run.locked === true : false
  }

  function isRunning(runId) {
    if (!runId) return false
    const run = runsById.value.get(runId) || (activeRun.value?.id === runId ? activeRun.value : null)
    if (!run) return false
    if (CHAIN_RUNNING_STATUSES.has(run.status)) return true
    if (CHAIN_FINISHED_STATUSES.has(run.status)) return false
    const order = run.resolved_order?.length ? run.resolved_order : run.project_ids || []
    const head = order[0]
    if (!head) return false
    return !CHAIN_UNSTARTED_MEMBER_STATUSES.has(run.project_statuses?.[head] ?? '')
  }

  function isReviewed(runId, pid) {
    if (!runId || !pid) return false
    return reviewedProjects.value.get(runId)?.has(pid) ?? false
  }

  function hasUnreviewedCompletedMember(r) {
    if (!r) return false
    const members = r.resolved_order?.length ? r.resolved_order : (r.project_ids || [])
    return members.some(
      (pid) => r.project_statuses?.[pid] === 'completed' && !isReviewed(r.id, pid),
    )
  }

  function isOutOfViewedScope(runId) {
    if (!runId || !scopedProductId.value) return false
    return !runsById.value.has(runId) && !reviewPendingById.value.has(runId)
  }

  const reviewPendingRun = computed(() => {
    const open = activeRun.value
    if (open && !isOutOfViewedScope(open.id) && hasUnreviewedCompletedMember(open)) return open
    for (const r of reviewPendingById.value.values()) {
      if (hasUnreviewedCompletedMember(r)) return r
    }
    return null
  })

  function markReviewed(runId, pid) {
    if (!runId || !pid) return
    const existing = reviewedProjects.value.get(runId)
    if (existing?.has(pid)) return
    const newSet = new Set(existing || [])
    newSet.add(pid)
    reviewedProjects.value = immutableMapSet(reviewedProjects.value, runId, newSet)
  }

  function mergeReviewedFromRun(run) {
    if (!run?.id) return
    const serverIds = Array.isArray(run.reviewed_project_ids) ? run.reviewed_project_ids : []
    if (!serverIds.length) return
    const existing = reviewedProjects.value.get(run.id)
    const merged = new Set(existing || [])
    let changed = false
    for (const pid of serverIds) {
      if (!merged.has(pid)) {
        merged.add(pid)
        changed = true
      }
    }
    if (changed) {
      reviewedProjects.value = immutableMapSet(reviewedProjects.value, run.id, merged)
    }
  }


  async function hydrate(statuses = ACTIVE_RUN_STATUSES, { allProducts = false } = {}) {
    loading.value = true
    error.value = null
    try {
      const viewedProductId = allProducts ? null : useProductStore().effectiveProductId
      const res = await api.sequenceRuns.list({
        status: statuses.join(','),
        include_review_pending: true,
        ...(viewedProductId ? { product_id: viewedProductId } : {}),
      })
      const runs = Array.isArray(res.data) ? res.data : res.data?.sequence_runs || []
      const next = new Map()
      const nextPending = new Map()
      for (const raw of runs) {
        const run = normalizeRun(raw)
        if (run) {
          if (ACTIVE_RUN_STATUSES.includes(run.status)) {
            next.set(run.id, run)
          } else {
            nextPending.set(run.id, run)
          }
          mergeReviewedFromRun(run)
        }
      }
      runsById.value = next
      reviewPendingById.value = nextPending
      scopedProductId.value = viewedProductId || null
      if (activeRun.value && next.has(activeRun.value.id)) {
        activeRun.value = next.get(activeRun.value.id)
      } else if (activeRun.value && isOutOfViewedScope(activeRun.value.id)) {
        activeRun.value = null
      }
      return activeRuns.value
    } catch (err) {
      error.value = err?.message || 'Failed to load chain runs'
      return []
    } finally {
      loading.value = false
    }
  }

  function setActiveRun(run) {
    const normalized = normalizeRun(run)
    activeRun.value = normalized
    if (normalized) {
      mergeReviewedFromRun(normalized)
      if (ACTIVE_RUN_STATUSES.includes(normalized.status) && !isOutOfViewedScope(normalized.id)) {
        runsById.value = immutableMapSet(runsById.value, normalized.id, normalized)
      }
    }
    return normalized
  }

  async function fetchRun(runId) {
    if (!runId) return null
    const res = await api.sequenceRuns.get(runId)
    return setActiveRun(res.data)
  }

  async function patchRun(runId, patch) {
    if (!runId) return null
    const res = await api.sequenceRuns.update(runId, patch)
    const run = normalizeRun(res.data) || normalizeRun({ id: runId, ...patch })
    if (run) {
      mergeReviewedFromRun(run)
      if (ACTIVE_RUN_STATUSES.includes(run.status)) {
        runsById.value = immutableMapSet(runsById.value, run.id, run)
      } else {
        runsById.value = immutableMapDelete(runsById.value, run.id)
      }
      if (activeRun.value && activeRun.value.id === run.id) activeRun.value = run
    }
    return run
  }

  async function markReviewedRemote(runId, pid) {
    if (!runId || !pid) return null
    const res = await api.sequenceRuns.markReviewed(runId, pid)
    const run = normalizeRun(res.data)
    if (run) mergeReviewedFromRun(run)
    return run
  }

  function notifyChainRetired(runId) {
    useNotificationStore().addNotification({
      id: `chain-retired:${runId}`,
      type: 'lifecycle',
      severity: 'info',
      title: 'Chain finished',
      message: 'This chain has finished; its record was retired.',
    })
  }

  async function handleSequenceUpdated(payload) {
    const runId = payload?.run_id || payload?.id
    const openRunId = activeRun.value?.id ?? null
    const wasKnownToBoard = !!runId && (runsById.value.has(runId) || reviewPendingById.value.has(runId))
    await hydrate()
    if (!runId) return
    const stillKnown = runsById.value.has(runId) || reviewPendingById.value.has(runId)
    if (openRunId === runId) {
      if (!stillKnown) {
        try {
          await fetchRun(runId)
        } catch {
          activeRun.value = null
          retiredRunNotice.value = { runId }
          notifyChainRetired(runId)
        }
      } else {
        activeRun.value = runsById.value.get(runId)
      }
    } else if (wasKnownToBoard && !stillKnown) {
      try {
        await api.sequenceRuns.get(runId)
      } catch {
        notifyChainRetired(runId)
      }
    }
  }

  function clearRetiredRunNotice() {
    retiredRunNotice.value = null
  }

  async function lockRun(runId) {
    return patchRun(runId, { locked: true })
  }

  async function unlockRun(runId) {
    return patchRun(runId, { locked: false })
  }

  async function stopChain(runId) {
    const res = await api.sequenceRuns.stop(runId)
    const stopped = normalizeRun(res.data)
    await hydrate()
    return stopped
  }

  async function deactivateChain(runId) {
    await api.sequenceRuns.deactivate(runId)
    await hydrate()
  }

  function clearActiveRun() {
    activeRun.value = null
  }

  function $reset() {
    runsById.value = new Map()
    activeRun.value = null
    reviewedProjects.value = new Map()
    reviewPendingById.value = new Map()
    scopedProductId.value = null
    loading.value = false
    error.value = null
  }

  function _testSeedRuns(rawRuns) {
    const next = new Map()
    for (const raw of rawRuns || []) {
      const run = normalizeRun(raw)
      if (run) next.set(run.id, run)
    }
    runsById.value = next
  }

  function _testSetActiveRun(raw) {
    activeRun.value = normalizeRun(raw)
  }

  function _testSeedReviewPending(rawRuns) {
    const next = new Map()
    for (const raw of rawRuns || []) {
      const run = normalizeRun(raw)
      if (run) next.set(run.id, run)
    }
    reviewPendingById.value = next
  }

  return {
    runsById,
    activeRun,
    reviewPendingById,
    retiredRunNotice,
    loading,
    error,
    activeRuns,
    activeChainProjectIds,
    isProjectInActiveChain,
    runForProject,
    projectChainStatus,
    isProjectRunLocked,
    isProjectStartable,
    isRunning,
    isReviewed,
    reviewPendingRun,
    hydrate,
    setActiveRun,
    fetchRun,
    patchRun,
    lockRun,
    unlockRun,
    stopChain,
    deactivateChain,
    handleSequenceUpdated,
    clearRetiredRunNotice,
    clearActiveRun,
    markReviewed,
    markReviewedRemote,
    $reset,
    _testSeedRuns,
    _testSetActiveRun,
    _testSeedReviewPending,
  }
})
