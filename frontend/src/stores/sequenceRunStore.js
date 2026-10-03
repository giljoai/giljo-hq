import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { immutableMapSet, immutableMapDelete } from './immutableHelpers'
import { useProductStore } from '@/stores/products'
import { useNotificationStore } from '@/stores/notifications'
import api from '@/services/api'
import { parseErrorResponse } from '@/utils/errorMessages'

const ACTIVE_RUN_STATUSES = ['pending', 'running', 'stalled']
const CHAIN_FINISHED_STATUSES = new Set(['completed', 'failed', 'terminated', 'cancelled'])
const CHAIN_UNSTARTED_MEMBER_STATUSES = new Set(['', 'pending', 'staged'])
const CHAIN_RUNNING_STATUSES = new Set(['running', 'stalled'])

function normalizeRun(raw) {
  if (!raw) return null
  const id = raw.id
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
    product_id: raw.product_id ?? null,
    created_at: raw.created_at ?? null,
    updated_at: raw.updated_at ?? null,
    locked: typeof raw.locked === 'boolean' ? raw.locked : false,
    chain_mission: typeof raw.chain_mission === 'string' ? raw.chain_mission : (raw.chain_mission ?? null),
    reviewed_project_ids: Array.isArray(raw.reviewed_project_ids) ? raw.reviewed_project_ids : [],
  }
}

export const useSequenceRunStore = defineStore('sequenceRun', () => {
  const runsById = ref(new Map())
  const reviewedProjects = ref(new Map())
  const reviewPendingById = ref(new Map())
  const loading = ref(false)
  const error = ref(null)

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
    const run = runsById.value.get(runId)
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

  const reviewPendingRun = computed(() => {
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
      if (!Array.isArray(res.data)) throw new Error('Chain run list reply is not a list')
      const runs = res.data
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
      return activeRuns.value
    } catch (err) {
      error.value = parseErrorResponse(err).message
      return []
    } finally {
      loading.value = false
    }
  }

  function withListedProduct(run) {
    const listed = run && !run.product_id && (runsById.value.get(run.id) || reviewPendingById.value.get(run.id))
    return listed ? { ...run, product_id: listed.product_id } : run
  }

  async function patchRun(runId, patch) {
    if (!runId) return null
    const res = await api.sequenceRuns.update(runId, patch)
    const run = withListedProduct(normalizeRun(res.data) || normalizeRun({ id: runId, ...patch }))
    if (run) {
      mergeReviewedFromRun(run)
      if (ACTIVE_RUN_STATUSES.includes(run.status)) {
        runsById.value = immutableMapSet(runsById.value, run.id, run)
      } else {
        runsById.value = immutableMapDelete(runsById.value, run.id)
      }
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
    const runId = payload?.run_id
    const wasKnownToBoard = !!runId && (runsById.value.has(runId) || reviewPendingById.value.has(runId))
    await hydrate()
    if (!runId) return
    const stillKnown = runsById.value.has(runId) || reviewPendingById.value.has(runId)
    if (wasKnownToBoard && !stillKnown) {
      try {
        await api.sequenceRuns.get(runId)
      } catch (error) {
        if (error?.response?.status === 404) {
          notifyChainRetired(runId)
        } else {
          useNotificationStore().addNotification({
            id: `chain-check-failed:${runId}`,
            type: 'lifecycle',
            severity: 'warning',
            title: 'Chain state unknown',
            message: `Could not confirm this chain's state: ${parseErrorResponse(error).message}`,
          })
        }
      }
    }
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

  function $reset() {
    runsById.value = new Map()
    reviewedProjects.value = new Map()
    reviewPendingById.value = new Map()
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
    reviewPendingById,
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
    patchRun,
    lockRun,
    unlockRun,
    stopChain,
    deactivateChain,
    handleSequenceUpdated,
    markReviewed,
    markReviewedRemote,
    $reset,
    _testSeedRuns,
    _testSeedReviewPending,
  }
})
