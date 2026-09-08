/**
 * sequenceRunStore.js — FE-6165f
 *
 * Pinia store for the durable election keystone of the Sequential Multi-Project
 * Runner. Election lives in the run record (a `SequenceRun` whose `project_ids`
 * holds the elected projects); this store is the read-back that makes election
 * SURVIVE navigation — without it, election lived only in `useSequenceRunner`'s
 * in-memory selection Map and was wiped on every route change (the §6B Req-1 gap).
 *
 * Modeled on the proven setup-store idiom (commHubStore / projectMessagesStore):
 * Map-backed state, immutable upserts, default `api` import. The cockpit needs the
 * full run object plus the active-election SET (not a bare run-id scalar), so we
 * hold both.
 *
 * Two distinct concerns (kept separate on purpose):
 *   - `runsById`  — the ACTIVE-election set (pending/running/stalled runs from
 *     `list`). Drives the locked "In chain" checkbox + pill on /projects +
 *     /roadmap. A run going terminal drops out on the next hydrate → checkbox
 *     unlocks automatically. NEVER writes ProjectStatus.ACTIVE (§3 invariant).
 *   - `activeRun` — the single run currently OPEN in the cockpit (any status,
 *     incl. terminal when viewing a finished run). Set by the cockpit.
 *
 * Edition scope: CE.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { immutableMapSet, immutableMapDelete } from './immutableHelpers'
import api from '@/services/api'

// Active-election statuses: a run in any of these locks its members' checkboxes.
// Mirrors the backend default for GET /sequence-runs?status= (BE-6165e).
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
    // FE-6171b: Stage lock flag. Default false so existing runs (pre-migration) are editable.
    locked: typeof raw.locked === 'boolean' ? raw.locked : false,
    // FE-6199 B1: canonical chain mission stored directly on the run.
    chain_mission: typeof raw.chain_mission === 'string' ? raw.chain_mission : (raw.chain_mission ?? null),
    // BE-9098: durable per-member review acknowledgment. Read back so the Review
    // badge survives refresh/navigation (previously client-only, wiped on reload).
    reviewed_project_ids: Array.isArray(raw.reviewed_project_ids) ? raw.reviewed_project_ids : [],
  }
}

export const useSequenceRunStore = defineStore('sequenceRun', () => {
  // ----- state -----
  /** Map<run_id, run> — the active-election set (pending/running/stalled). */
  const runsById = ref(new Map())
  /** The run currently open in the cockpit (any status). Null when none. */
  const activeRun = ref(null)
  /**
   * Map<run_id, Set<project_id>> — chain review tracking.
   * BE-9098: now SERVER-BACKED. Seeded from each run's reviewed_project_ids on
   * hydrate/fetch (mergeReviewedFromRun, union so optimistic entries survive) and
   * written through markReviewedRemote(), so it survives refresh/navigation. Local
   * markReviewed() remains the optimistic path (instant badge flip before the POST
   * round-trips). Uses immutable Map replacement so Vue computed that read
   * isReviewed() re-evaluate reactively — a plain Set.add() would leave them stale.
   */
  const reviewedProjects = ref(new Map())
  /**
   * Map<run_id, run> — FE-9104: TERMINAL runs that still have a completed-but-
   * unreviewed member, surfaced by the server (`include_review_pending=true`) on
   * hydrate. Kept SEPARATE from runsById on purpose: these are finished runs, so
   * they must NOT re-lock "In chain" checkboxes or count as active chains. This is
   * the cold-refresh source `reviewPendingRun` reads when `activeRun` is null.
   */
  const reviewPendingById = ref(new Map())
  const loading = ref(false)
  const error = ref(null)
  /**
   * BE-9540: { runId } | null. Set when handleSequenceUpdated discovers the
   * OPEN cockpit run is genuinely gone (purged, not merely retired to a
   * terminal status) -- an open chain view should meet this with a designed
   * terminal state, not a raw 404 storm from further interaction with a row
   * that no longer exists. Cleared by the consumer (useChainContext) once
   * handled; a fresh null->{runId} transition is what the watcher fires on.
   */
  const retiredRunNotice = ref(null)

  // ----- getters -----

  /** All active-election runs, as an array. */
  const activeRuns = computed(() => Array.from(runsById.value.values()))

  /** Flat union of every project_id across all active-election runs. */
  const activeChainProjectIds = computed(() => {
    const ids = new Set()
    for (const run of runsById.value.values()) {
      for (const pid of run.project_ids) ids.add(pid)
    }
    return Array.from(ids)
  })

  /**
   * Is this project a member of an active (in-flight) chain run? Drives the
   * locked + force-ticked "In chain" checkbox. Reads reactive state, so callers
   * in templates re-evaluate when runsById changes.
   */
  function isProjectInActiveChain(projectId) {
    if (!projectId) return false
    for (const run of runsById.value.values()) {
      if (run.project_ids.includes(projectId)) return true
    }
    return false
  }

  /** The active run that contains this project, or null. */
  function runForProject(projectId) {
    if (!projectId) return null
    for (const run of runsById.value.values()) {
      if (run.project_ids.includes(projectId)) return run
    }
    return null
  }

  /** The per-project status (`project_statuses[pid]`) within its active run, or null. */
  function projectChainStatus(projectId) {
    const run = runForProject(projectId)
    return run ? run.project_statuses?.[projectId] ?? null : null
  }

  /**
   * FE-6171b: Is the run that contains this project in the locked (Staged) tier?
   * Returns true only when `run.locked === true`; false when editing (no run,
   * locked=false) or when the project is not in any active chain.
   * This is the ONLY signal that drives tickbox disable on /projects + /roadmap.
   */
  function isProjectRunLocked(projectId) {
    const run = runForProject(projectId)
    return run ? run.locked === true : false
  }

  /**
   * Has this project been reviewed in the given chain run's review flow?
   * Client-side only — ephemeral, reset on refresh (acceptable; project is
   * already completed, review is non-gating).
   */
  function isReviewed(runId, pid) {
    if (!runId || !pid) return false
    return reviewedProjects.value.get(runId)?.has(pid) ?? false
  }

  /**
   * True when a run has ≥1 member whose chain status is 'completed' and which is
   * not yet reviewed (reads reviewedProjects, so optimistic marks release it too).
   */
  function hasUnreviewedCompletedMember(r) {
    if (!r) return false
    const members = r.resolved_order?.length ? r.resolved_order : (r.project_ids || [])
    return members.some(
      (pid) => r.project_statuses?.[pid] === 'completed' && !isReviewed(r.id, pid),
    )
  }

  /**
   * FE-6199 / FE-9104 nav fix: the run that is finished-but-still-needs-review, or null.
   *
   * Used by NavigationDrawer to keep the Jobs link alive after the conductor
   * flips the run to terminal (which drops it from activeRuns). Returns the open
   * cockpit run when it has at least one completed, unreviewed member; else the
   * most-recent server-surfaced review-pending run (the cold-refresh path — see
   * reviewPendingById). Returns null once every completed member is reviewed,
   * releasing the link so no infinite bounce is possible.
   *
   * FE-6199 covered the in-session case via activeRun (populated by an open
   * cockpit / a `?run=` visit). FE-9104 adds the cold-refresh case: after a full
   * page reload with no `?run=`, activeRun is null, so we read reviewPendingById,
   * which hydrate() seeds from the server's include_review_pending listing.
   *
   * Solo deletion-test: no chain runs → activeRun null AND reviewPendingById empty
   * → returns null immediately; nav behaviour byte-identical to pre-fix.
   */
  const reviewPendingRun = computed(() => {
    if (hasUnreviewedCompletedMember(activeRun.value)) return activeRun.value
    for (const r of reviewPendingById.value.values()) {
      if (hasUnreviewedCompletedMember(r)) return r
    }
    return null
  })

  /**
   * Mark a chain member project as reviewed for a given run.
   * Idempotent: calling twice for the same (runId, pid) is a no-op.
   * Uses immutable Map replacement so Vue ref-tracking re-evaluates any
   * computed that reads isReviewed() — a plain Set.add() would be untracked.
   */
  function markReviewed(runId, pid) {
    if (!runId || !pid) return
    const existing = reviewedProjects.value.get(runId)
    if (existing?.has(pid)) return // idempotent
    const newSet = new Set(existing || [])
    newSet.add(pid)
    reviewedProjects.value = immutableMapSet(reviewedProjects.value, runId, newSet)
  }

  /**
   * BE-9098: seed reviewedProjects from a run's server-persisted
   * reviewed_project_ids. UNION with any existing (optimistic) entries so an
   * in-flight local mark is never clobbered by a hydrate that predates its POST.
   * Immutable Map replacement only when something actually changed (keeps the ref
   * stable so unrelated computeds don't churn). This is what makes the badge
   * survive refresh: fetchRun/hydrate call it, so isReviewed() is true with NO
   * prior local markReviewed().
   */
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

  // ----- actions -----

  /**
   * Hydrate the active-election set. Rebuilds runsById from scratch so a run
   * that has gone terminal (and therefore dropped out of the status filter)
   * disappears — unlocking its members' checkboxes with no per-project write.
   *
   * FE-9104: also requests include_review_pending=true so the server appends
   * terminal runs awaiting review. Those (status ∉ ACTIVE_RUN_STATUSES) are routed
   * to reviewPendingById — NOT runsById — so they keep the Jobs review link alive
   * after a cold refresh without re-locking any checkbox or counting as active.
   */
  async function hydrate(statuses = ACTIVE_RUN_STATUSES) {
    loading.value = true
    error.value = null
    try {
      const res = await api.sequenceRuns.list({
        status: statuses.join(','),
        include_review_pending: true,
      })
      // BE-6165e returns a BARE ARRAY of serialized runs (not wrapped).
      const runs = Array.isArray(res.data) ? res.data : res.data?.sequence_runs || []
      const next = new Map()
      const nextPending = new Map()
      for (const raw of runs) {
        const run = normalizeRun(raw)
        if (run) {
          // Active-status runs drive the election set; terminal ones (only present
          // when include_review_pending surfaced them) drive the review-link source.
          if (ACTIVE_RUN_STATUSES.includes(run.status)) {
            next.set(run.id, run)
          } else {
            nextPending.set(run.id, run)
          }
          mergeReviewedFromRun(run) // BE-9098: seed durable review acks from the server
        }
      }
      runsById.value = next
      reviewPendingById.value = nextPending
      // Keep the cockpit's open run in sync if it's part of the active set.
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

  /** Set the cockpit's open run (the run the cockpit fetched via ?run=<id>). */
  function setActiveRun(run) {
    const normalized = normalizeRun(run)
    activeRun.value = normalized
    if (normalized) {
      // BE-9098: seed durable review acks so the badge is correct immediately on
      // fetch (the exact refresh-survival path — no prior local markReviewed needed).
      mergeReviewedFromRun(normalized)
      if (ACTIVE_RUN_STATUSES.includes(normalized.status)) {
        runsById.value = immutableMapSet(runsById.value, normalized.id, normalized)
      }
    }
    return normalized
  }

  /** Fetch a single run by id and set it as the cockpit's open run. */
  async function fetchRun(runId) {
    if (!runId) return null
    const res = await api.sequenceRuns.get(runId)
    return setActiveRun(res.data)
  }

  /**
   * PATCH a run (the single write seam used by the cockpit + lifecycle flows).
   * Refreshes both the cockpit run and the election-set entry. A run that drops
   * to a terminal status is removed from runsById here too.
   */
  async function patchRun(runId, patch) {
    if (!runId) return null
    const res = await api.sequenceRuns.update(runId, patch)
    const run = normalizeRun(res.data) || normalizeRun({ id: runId, ...patch })
    if (run) {
      mergeReviewedFromRun(run) // BE-9098: keep durable review acks in sync on writes
      if (ACTIVE_RUN_STATUSES.includes(run.status)) {
        runsById.value = immutableMapSet(runsById.value, run.id, run)
      } else {
        runsById.value = immutableMapDelete(runsById.value, run.id)
      }
      if (activeRun.value && activeRun.value.id === run.id) activeRun.value = run
    }
    return run
  }

  /**
   * BE-9098: persist a member review to the server so it survives refresh.
   * The caller marks locally (optimistic, instant badge flip) BEFORE calling this;
   * here we POST the durable write and merge the authoritative server array back
   * (idempotent). Throws on failure so the caller can surface a toast — the
   * optimistic local mark stays (non-gating; it self-corrects on next hydrate).
   */
  async function markReviewedRemote(runId, pid) {
    if (!runId || !pid) return null
    const res = await api.sequenceRuns.markReviewed(runId, pid)
    const run = normalizeRun(res.data)
    if (run) mergeReviewedFromRun(run)
    return run
  }

  /**
   * WS `sequence:updated` handler. The event carries ONLY { run_id } (BE-6165c),
   * so we re-fetch authoritative state: re-hydrate the active-election set (drops
   * terminal runs) and refresh the cockpit's open run if it matches.
   *
   * FE-6199 (live-update hardening): explicitly push the fresh runsById entry into
   * activeRun for STILL-ACTIVE runs so useChainContext watchers see chain_mission /
   * locked / status changes immediately.  hydrate() already does a conditional sync
   * (only when activeRun.value is non-null), but making the still-active branch
   * explicit here is belt-and-suspenders against any future regression in that path.
   */
  async function handleSequenceUpdated(payload) {
    const runId = payload?.run_id || payload?.id
    await hydrate()
    if (runId && activeRun.value && activeRun.value.id === runId) {
      if (!runsById.value.has(runId)) {
        // Open run went terminal (dropped from the active set) — refetch so the
        // cockpit reflects the final status instead of going stale.
        try {
          await fetchRun(runId)
        } catch {
          // BE-9540: the run is genuinely GONE (purged at conductor-finale time),
          // not merely retired to a terminal status fetchRun could still return.
          // Keeping the last-known activeRun would leave the view pointing at a
          // row that no longer exists. Clear it and raise a notice so the
          // consumer (useChainContext) can meet this with a designed terminal
          // state instead.
          activeRun.value = null
          retiredRunNotice.value = { runId }
        }
      } else {
        // Run is still active: pull the freshly-hydrated entry into activeRun.
        // This guarantees that chain_mission / locked writes by the conductor reach
        // the cockpit's reactive chain immediately (FE-6199 chain staging live-fill).
        activeRun.value = runsById.value.get(runId)
      }
    }
  }

  /** BE-9540: consumer-side ack that a retired-run notice has been handled. */
  function clearRetiredRunNotice() {
    retiredRunNotice.value = null
  }

  /**
   * FE-6171b: Lock the run (Stage action). PATCHes locked=true.
   * Returns the updated run, or throws on error.
   */
  async function lockRun(runId) {
    return patchRun(runId, { locked: true })
  }

  /**
   * FE-6171b: Unlock the run (Unstage action). PATCHes locked=false.
   * The chain stays intact — this does NOT dissolve or release the run.
   * The BE refuses with 422 at ultralock tier (running/stalled or any member staging_complete).
   * Returns the updated run, or throws on error.
   */
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

  // ----- test-only helpers (tree-shaken in prod; used by sequenceRunStore.spec.js) -----
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

  // FE-9104: seed the review-pending (terminal) map directly, mirroring what
  // hydrate() does with server-surfaced include_review_pending runs.
  function _testSeedReviewPending(rawRuns) {
    const next = new Map()
    for (const raw of rawRuns || []) {
      const run = normalizeRun(raw)
      if (run) next.set(run.id, run)
    }
    reviewPendingById.value = next
  }

  return {
    // state
    runsById,
    activeRun,
    reviewPendingById,
    retiredRunNotice,
    loading,
    error,
    // getters
    activeRuns,
    activeChainProjectIds,
    isProjectInActiveChain,
    runForProject,
    projectChainStatus,
    isProjectRunLocked,
    isReviewed,
    reviewPendingRun,
    // actions
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
    // test helpers
    _testSeedRuns,
    _testSetActiveRun,
    _testSeedReviewPending,
  }
})
