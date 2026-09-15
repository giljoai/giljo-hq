import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { immutableMapSet, immutableMapDelete } from './immutableHelpers'
import api from '@/services/api'

const ACTIVE_RUN_STATUSES = ['pending', 'running', 'stalled']

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

  function isProjectRunLocked(projectId) {
    const run = runForProject(projectId)
    return run ? run.locked === true : false
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
    if (hasUnreviewedCompletedMember(activeRun.value)) return activeRun.value
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


  async function hydrate(statuses = ACTIVE_RUN_STATUSES) {
    loading.value = true
    error.value = null
    try {
      const res = await api.sequenceRuns.list({
        status: statuses.join(','),
        include_review_pending: true,
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
      if (activeRun.value && next.has(activeRun.value.id)) {
        activeRun.value = next.get(activeRun.value.id)
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
      if (ACTIVE_RUN_STATUSES.includes(normalized.status)) {
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

  async function handleSequenceUpdated(payload) {
    const runId = payload?.run_id || payload?.id
    await hydrate()
    if (runId && activeRun.value && activeRun.value.id === runId) {
      if (!runsById.value.has(runId)) {
        try {
          await fetchRun(runId)
        } catch {
          activeRun.value = null
          retiredRunNotice.value = { runId }
        }
      } else {
        activeRun.value = runsById.value.get(runId)
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

  function clearActiveRun() {
    activeRun.value = null
  }

  function $reset() {
    runsById.value = new Map()
    activeRun.value = null
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
    isReviewed,
    reviewPendingRun,
    hydrate,
    setActiveRun,
    fetchRun,
    patchRun,
    lockRun,
    unlockRun,
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
