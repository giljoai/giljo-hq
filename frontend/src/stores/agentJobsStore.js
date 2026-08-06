import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import isEqual from 'lodash-es/isEqual'
import debounce from 'lodash-es/debounce'
import api from '@/services/api'
import { AGENT_STATUS_PRIORITY } from '@/utils/constants'

function ensureArray(value) {
  return Array.isArray(value) ? value : []
}

function normalizeJob(rawJob) {
  const job_id = rawJob?.job_id || rawJob?.id || rawJob?.agent_id
  // Handover 0462: Prefer agent_id (executor UUID) - always present and unique after spawn
  // This prevents unique_key mismatches between WebSocket and API data
  // Handover 0700i: Removed instance_number - use agent_id as unique_key
  const unique_key = rawJob?.agent_id || rawJob?.execution_id || job_id
  return {
    ...rawJob,
    job_id,
    unique_key,
    messages_sent_count: rawJob?.messages_sent_count ?? 0,
    messages_waiting_count: rawJob?.messages_waiting_count ?? 0,
    // BE-9273: the subset of messages_waiting_count that is genuinely
    // requires_action + non-auto_generated (blocks complete_job) -- lets the
    // AgentRow badge distinguish "waiting on THIS agent" from plain unread.
    action_required_unread: rawJob?.action_required_unread ?? 0,
    messages_read_count: rawJob?.messages_read_count ?? 0,
  }
}

function createNextMapWith(map, key, value) {
  const next = new Map(map)
  next.set(key, value)
  return next
}

function createNextMapWithout(map, key) {
  const next = new Map(map)
  next.delete(key)
  return next
}

export const useAgentJobsStore = defineStore('agentJobsDomain', () => {
  const jobsById = ref(new Map())

  const jobCount = computed(() => jobsById.value.size)

  const jobs = computed(() => Array.from(jobsById.value.values()))

  const sortedJobs = computed(() => {
    const list = Array.from(jobsById.value.values())
    list.sort((a, b) => {
      const aPriority = AGENT_STATUS_PRIORITY[a.status] ?? 999
      const bPriority = AGENT_STATUS_PRIORITY[b.status] ?? 999

      if (aPriority !== bPriority) return aPriority - bPriority

      // Within same status group, apply timestamp-based sorting
      if (a.status === 'working' && b.status === 'working') {
        // Working: most recently started on top (descending by started_at)
        const aStarted = a.started_at ? new Date(a.started_at).getTime() : 0
        const bStarted = b.started_at ? new Date(b.started_at).getTime() : 0
        if (aStarted !== bStarted) return bStarted - aStarted  // descending
      }

      if ((a.status === 'complete' || a.status === 'completed') &&
          (b.status === 'complete' || b.status === 'completed')) {
        // Completed: most recently completed on top (descending by completed_at)
        const aCompleted = a.completed_at ? new Date(a.completed_at).getTime() : 0
        const bCompleted = b.completed_at ? new Date(b.completed_at).getTime() : 0
        if (aCompleted !== bCompleted) return bCompleted - aCompleted  // descending
      }

      // Orchestrators first within same status/timestamp
      const aIsOrchestrator = a.agent_display_name === 'orchestrator' ? 0 : 1
      const bIsOrchestrator = b.agent_display_name === 'orchestrator' ? 0 : 1
      if (aIsOrchestrator !== bIsOrchestrator) return aIsOrchestrator - bIsOrchestrator

      return (a.agent_display_name || '').localeCompare(b.agent_display_name || '')
    })

    return list
  })

  function getJob(jobId) {
    if (!jobId) return null
    // Handover 0700i: Removed instanceNumber parameter
    // Try direct lookup (might be unique_key already)
    if (jobsById.value.has(jobId)) {
      return jobsById.value.get(jobId)
    }
    // Fallback: find first job with matching job_id
    for (const job of jobsById.value.values()) {
      if (job.job_id === jobId) {
        return job
      }
    }
    return null
  }

  function setJobs(rows = []) {
    const next = new Map()
    for (const rawJob of ensureArray(rows)) {
      const job = normalizeJob(rawJob)
      if (!job.unique_key) continue

      // Handover 0463: Only preserve identity fields from existing entry
      // This prevents "??" avatars when API response lacks identity fields
      const existing = jobsById.value.get(job.unique_key)
      if (existing) {
        job.agent_display_name = job.agent_display_name || existing.agent_display_name
        job.agent_name = job.agent_name || existing.agent_name
      }

      next.set(job.unique_key, job)
    }
    jobsById.value = next
  }

  function upsertJob(patch) {
    const jobId = patch?.job_id || patch?.id || patch?.agent_id
    const agentId = patch?.agent_id
    if (!jobId && !agentId) return

    // CRITICAL FIX: Find existing job FIRST before computing unique_key
    // This prevents creating duplicates when WebSocket events use different ID formats
    // Handover 0700i: Removed instance_number matching
    let existingJob = null
    let existingKey = null

    // 1. Try execution_id (most specific)
    if (patch?.execution_id && jobsById.value.has(patch.execution_id)) {
      existingKey = patch.execution_id
      existingJob = jobsById.value.get(existingKey)
    }

    // 2. Try unique_key from patch
    if (!existingJob && patch?.unique_key && jobsById.value.has(patch.unique_key)) {
      existingKey = patch.unique_key
      existingJob = jobsById.value.get(existingKey)
    }

    // 3. Search by agent_id (executor UUID - used in WebSocket events)
    if (!existingJob && agentId) {
      for (const [key, job] of jobsById.value.entries()) {
        if (job.agent_id === agentId) {
          existingKey = key
          existingJob = job
          break
        }
      }
    }

    // 4. Search by job_id (work order UUID)
    if (!existingJob && jobId) {
      for (const [key, job] of jobsById.value.entries()) {
        if (job.job_id === jobId) {
          existingKey = key
          existingJob = job
          break
        }
      }
    }

    // Compute unique_key only if no existing job found (new entry)
    const uniqueKey = existingKey || patch?.execution_id || patch?.unique_key || jobId

    // Handover 0388: Filter undefined values to prevent state corruption
    // Spread operator preserves undefined, which overwrites existing valid data
    const cleanPatch = Object.fromEntries(
      Object.entries(patch || {}).filter(([_, v]) => v !== undefined)
    )

    const previous = existingJob || jobsById.value.get(uniqueKey)
    const nextJob = normalizeJob({ ...(previous || {}), ...cleanPatch, job_id: jobId || previous?.job_id })

    // Handover 0818 Phase 1: Use deep equality (lodash isEqual) instead of
    // JSON.stringify to handle key ordering, undefined, and circular refs.
    if (previous && isEqual(previous, nextJob)) {
      return
    }

    // Use existing key if we found one, otherwise use the computed/normalized key
    const finalKey = existingKey || nextJob.unique_key
    jobsById.value = createNextMapWith(jobsById.value, finalKey, nextJob)
  }

  // =========================
  // Handover 0818 Phase 2: Debounced updates for minor WebSocket events
  // =========================

  // Pending patches keyed by unique_key, merged until flush
  const pendingUpdates = new Map()

  /**
   * Flush all queued pending updates by calling upsertJob for each.
   * Exposed publicly for testability and for immediate handlers to drain
   * pending state before their own upsert.
   */
  function flushPendingUpdates() {
    if (pendingUpdates.size === 0) return
    for (const [, patch] of pendingUpdates) {
      upsertJob(patch)
    }
    pendingUpdates.clear()
  }

  // Debounced version of flush -- batches rapid-fire minor events (~300ms)
  const debouncedFlush = debounce(flushPendingUpdates, 300)

  /**
   * Queue a patch for debounced application. Resolves the unique_key,
   * merges into any existing pending patch for the same key, then
   * schedules a debounced flush.
   */
  function upsertJobDebounced(patch) {
    const jobId = patch?.job_id || patch?.id || patch?.agent_id
    const agentId = patch?.agent_id

    // Resolve the unique_key the same way upsertJob does
    let uniqueKey = null

    if (patch?.execution_id && jobsById.value.has(patch.execution_id)) {
      uniqueKey = patch.execution_id
    }
    if (!uniqueKey && patch?.unique_key && jobsById.value.has(patch.unique_key)) {
      uniqueKey = patch.unique_key
    }
    if (!uniqueKey && agentId) {
      for (const [key, job] of jobsById.value.entries()) {
        if (job.agent_id === agentId) {
          uniqueKey = key
          break
        }
      }
    }
    if (!uniqueKey && jobId) {
      for (const [key, job] of jobsById.value.entries()) {
        if (job.job_id === jobId) {
          uniqueKey = key
          break
        }
      }
    }
    if (!uniqueKey) {
      uniqueKey = patch?.execution_id || patch?.unique_key || jobId
    }

    if (!uniqueKey) return

    // Filter undefined values before merging to prevent overwriting
    // valid pending data with undefined (mirrors upsertJob's cleanPatch logic)
    const cleanPatch = Object.fromEntries(
      Object.entries(patch || {}).filter(([_, v]) => v !== undefined)
    )

    // Merge with any existing pending patch for this key
    const existing = pendingUpdates.get(uniqueKey)
    if (existing) {
      pendingUpdates.set(uniqueKey, { ...existing, ...cleanPatch })
    } else {
      pendingUpdates.set(uniqueKey, { ...cleanPatch })
    }

    debouncedFlush()
  }

  /**
   * Flush any pending debounced updates for a specific job key.
   * Used by immediate handlers (e.g. handleStatusChanged) to ensure
   * pending minor updates are applied before the lifecycle transition.
   */
  function flushPendingForJob(uniqueKey) {
    if (!uniqueKey || !pendingUpdates.has(uniqueKey)) return
    const patch = pendingUpdates.get(uniqueKey)
    pendingUpdates.delete(uniqueKey)
    upsertJob(patch)
  }

  // =========================
  // FE-9184: live "Messages Waiting" refresh (hub-backed)
  // =========================
  // A hub thread_message WS event only says "a post landed" — the authoritative
  // per-agent waiting counts live in the /jobs REST response (BE-6200 GROUP BY).
  // Refetch once per quiet window and patch ONLY messages_waiting_count +
  // action_required_unread (BE-9273: same REST row, same GROUP BY family) onto
  // jobs already in the store: count-only so a stale REST row can never regress
  // fresher WS lifecycle state, existing-only so a late or cross-project row can
  // never create a ghost entry (Handover 0463).

  async function fetchWaitingCounts(projectId) {
    let rows = []
    try {
      const response = await api.agentJobs.list(projectId)
      const data = response?.data
      rows = Array.isArray(data) ? data : data?.jobs || data?.rows || []
    } catch (error) {
      // eslint-disable-next-line no-console
      console.debug('[agentJobsStore] messages-waiting refresh failed (non-fatal):', error)
      return
    }
    for (const raw of ensureArray(rows)) {
      const key = resolveJobId(raw?.agent_id) || resolveJobId(raw?.job_id || raw?.id)
      if (!key) continue
      const previous = jobsById.value.get(key)
      if (!previous) continue
      const count = raw?.messages_waiting_count ?? 0
      const actionRequiredCount = raw?.action_required_unread ?? 0
      if (
        (previous.messages_waiting_count ?? 0) === count &&
        (previous.action_required_unread ?? 0) === actionRequiredCount
      ) {
        continue
      }
      // Handover 0463: spread previous to preserve identity fields
      upsertJob({
        ...previous,
        messages_waiting_count: count,
        action_required_unread: actionRequiredCount,
      })
    }
  }

  // maxWait bounds staleness during sustained agent chatter: at most one fetch
  // per 3s while messages keep arriving, one 500ms after the burst goes quiet.
  const debouncedFetchWaitingCounts = debounce(fetchWaitingCounts, 500, { maxWait: 3000 })

  function refreshMessagesWaitingCounts(projectId) {
    if (!projectId) return
    debouncedFetchWaitingCounts(projectId)
  }

  function removeJob(uniqueKeyOrJobId) {
    if (!uniqueKeyOrJobId) return
    // Try direct removal by unique_key
    if (jobsById.value.has(uniqueKeyOrJobId)) {
      jobsById.value = createNextMapWithout(jobsById.value, uniqueKeyOrJobId)
      return
    }
    // Fallback: find and remove by job_id
    for (const [key, job] of jobsById.value.entries()) {
      if (job.job_id === uniqueKeyOrJobId) {
        jobsById.value = createNextMapWithout(jobsById.value, key)
        return
      }
    }
  }

  // =========================
  // WebSocket event handlers
  // =========================

  function handleCreated(payload) {
    upsertJob(payload)
  }

  function handleUpdated(payload) {
    upsertJob(payload)
  }

  function handleStatusChanged(payload) {
    // Handover 0462 hardening (from 0463 recommendation):
    // Only update existing jobs, don't create new ones from status events
    // This prevents ghost rows from cross-project event leaks
    const existingKey = resolveJobId(payload?.job_id) || resolveJobId(payload?.agent_id)
    if (!existingKey) {
      // Job not in store - this might be cross-project leak, ignore
      // eslint-disable-next-line no-console
      console.debug('[handleStatusChanged] Ignoring status for unknown job:', payload?.job_id)
      return
    }

    // Handover 0818: Flush any pending debounced updates for this job
    // before applying the immediate status transition, so counters/progress
    // are not lost when a lifecycle event overtakes queued minor events.
    flushPendingForJob(existingKey)

    upsertJob(payload)
  }

  // Handover 0386: Handle progress updates from job:progress_update WebSocket events
  // Progress is now sent directly via WebSocket, NOT via message system
  // Handover 0388: Conditionally build updates to prevent undefined corruption
  // Handover 0401: Transform todo_steps array to steps summary object
  // Handover 0402: Store todo_items for Plan/TODOs tab display
  // Handover 0462: Include identity fields to prevent "??" avatar bug from race conditions
  function handleProgressUpdate(payload) {
    if (!payload?.job_id) return

    const updates = {
      job_id: payload.job_id,
      progress: payload.progress,
      current_task: payload.current_task,
      last_progress_at: payload.last_progress_at,
    }

    // Handover 0462: Include identity fields to prevent "??" avatar bug
    // If this event arrives before agent:created, these fields ensure the entry is complete
    if (payload.agent_display_name) {
      updates.agent_display_name = payload.agent_display_name
    }
    if (payload.agent_name) {
      updates.agent_name = payload.agent_name
    }
    if (payload.agent_id) {
      updates.agent_id = payload.agent_id
    }

    // Only add job_metadata when todo_steps exists (prevents undefined overwrite)
    // Handover 0401: Handle both object format { total_steps, completed_steps }
    // and array format [{ status: 'done' }, ...]
    if (payload.todo_steps) {
      updates.job_metadata = { todo_steps: payload.todo_steps }

      if (Array.isArray(payload.todo_steps)) {
        // Array format: count completed, skipped vs total
        const completed = payload.todo_steps.filter(
          (s) => s.status === 'done' || s.status === 'completed'
        ).length
        const skipped = payload.todo_steps.filter(
          (s) => s.status === 'skipped'
        ).length
        updates.steps = {
          completed,
          skipped,
          total: payload.todo_steps.length,
        }
      } else if (typeof payload.todo_steps === 'object') {
        // Object format from backend: { total_steps, completed_steps, skipped_steps }
        const total = payload.todo_steps.total_steps
        const completed = payload.todo_steps.completed_steps
        const skipped = payload.todo_steps.skipped_steps || 0
        if (typeof total === 'number' && typeof completed === 'number') {
          updates.steps = { completed, skipped, total }
        }
      }
    }

    // Handover 0402: Store todo_items array for display in Plan/TODOs tab
    // Backend sends: [{ content: "...", status: "pending|in_progress|completed" }, ...]
    if (payload.todo_items && Array.isArray(payload.todo_items)) {
      updates.todo_items = payload.todo_items
    }

    // Handover 0818: Use debounced path for minor progress events
    upsertJobDebounced(updates)
  }

  function resolveJobId(identifier) {
    if (!identifier) return null

    // Direct match by unique_key
    if (jobsById.value.has(identifier)) {
      return identifier
    }

    // Check by agent_id (executor UUID from messaging) - return unique_key
    for (const job of jobsById.value.values()) {
      if (job.agent_id === identifier) {
        return job.unique_key
      }
    }

    // Check by job_id - return unique_key of first match
    for (const job of jobsById.value.values()) {
      if (job.job_id === identifier) {
        return job.unique_key
      }
    }

    // Legacy fallback: from_agent may be agent_display_name (e.g., "orchestrator").
    for (const job of jobsById.value.values()) {
      if (job.agent_display_name === identifier || job.agent_name === identifier) {
        return job.unique_key
      }
    }

    return null
  }

  function $reset() {
    jobsById.value = new Map()
  }

  // Create a proxy object that maintains .value structure
  const jobsByIdProxy = new Proxy(
    {},
    {
      get: (target, prop) => {
        if (prop === 'value') {
          return jobsById.value
        }
        return undefined
      },
    }
  )

  return {
    // state
    jobsById: jobsByIdProxy,

    // getters
    jobs,
    sortedJobs,
    jobCount,

    // selectors
    getJob,
    resolveJobId,

    // actions
    setJobs,
    upsertJob,
    removeJob,
    refreshMessagesWaitingCounts,

    // ws handlers
    handleCreated,
    handleUpdated,
    handleStatusChanged,
    handleProgressUpdate,

    // debounce (exposed for testability)
    flushPendingUpdates,

    // lifecycle
    $reset,
  }
})
