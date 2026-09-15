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
  const unique_key = rawJob?.agent_id || rawJob?.execution_id || job_id
  return {
    ...rawJob,
    job_id,
    unique_key,
    messages_sent_count: rawJob?.messages_sent_count ?? 0,
    messages_waiting_count: rawJob?.messages_waiting_count ?? 0,
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

      if (a.status === 'working' && b.status === 'working') {
        const aStarted = a.started_at ? new Date(a.started_at).getTime() : 0
        const bStarted = b.started_at ? new Date(b.started_at).getTime() : 0
        if (aStarted !== bStarted) return bStarted - aStarted
      }

      if ((a.status === 'complete' || a.status === 'completed') &&
          (b.status === 'complete' || b.status === 'completed')) {
        const aCompleted = a.completed_at ? new Date(a.completed_at).getTime() : 0
        const bCompleted = b.completed_at ? new Date(b.completed_at).getTime() : 0
        if (aCompleted !== bCompleted) return bCompleted - aCompleted
      }

      const aIsOrchestrator = a.agent_display_name === 'orchestrator' ? 0 : 1
      const bIsOrchestrator = b.agent_display_name === 'orchestrator' ? 0 : 1
      if (aIsOrchestrator !== bIsOrchestrator) return aIsOrchestrator - bIsOrchestrator

      return (a.agent_display_name || '').localeCompare(b.agent_display_name || '')
    })

    return list
  })

  function getJob(jobId) {
    if (!jobId) return null
    if (jobsById.value.has(jobId)) {
      return jobsById.value.get(jobId)
    }
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

      const existing = jobsById.value.get(job.unique_key)
      if (existing) {
        job.agent_display_name = job.agent_display_name || existing.agent_display_name
        job.agent_name = job.agent_name || existing.agent_name
      }

      next.set(job.unique_key, job)
    }
    jobsById.value = next
    discardPendingUpdates()
  }

  function upsertJob(patch) {
    const jobId = patch?.job_id || patch?.id || patch?.agent_id
    const agentId = patch?.agent_id
    if (!jobId && !agentId) return

    let existingJob = null
    let existingKey = null

    if (patch?.execution_id && jobsById.value.has(patch.execution_id)) {
      existingKey = patch.execution_id
      existingJob = jobsById.value.get(existingKey)
    }

    if (!existingJob && patch?.unique_key && jobsById.value.has(patch.unique_key)) {
      existingKey = patch.unique_key
      existingJob = jobsById.value.get(existingKey)
    }

    if (!existingJob && agentId) {
      for (const [key, job] of jobsById.value.entries()) {
        if (job.agent_id === agentId) {
          existingKey = key
          existingJob = job
          break
        }
      }
    }

    if (!existingJob && jobId) {
      for (const [key, job] of jobsById.value.entries()) {
        if (job.job_id === jobId) {
          existingKey = key
          existingJob = job
          break
        }
      }
    }

    const uniqueKey = existingKey || patch?.execution_id || patch?.unique_key || jobId

    const cleanPatch = Object.fromEntries(
      Object.entries(patch || {}).filter(([_, v]) => v !== undefined)
    )

    const previous = existingJob || jobsById.value.get(uniqueKey)
    const nextJob = normalizeJob({ ...(previous || {}), ...cleanPatch, job_id: jobId || previous?.job_id })

    if (previous && isEqual(previous, nextJob)) {
      return
    }

    const finalKey = existingKey || nextJob.unique_key
    jobsById.value = createNextMapWith(jobsById.value, finalKey, nextJob)
  }


  const pendingUpdates = new Map()

  function flushPendingUpdates() {
    if (pendingUpdates.size === 0) return
    for (const [, patch] of pendingUpdates) {
      upsertJob(patch)
    }
    pendingUpdates.clear()
  }

  const debouncedFlush = debounce(flushPendingUpdates, 300)

  function discardPendingUpdates() {
    pendingUpdates.clear()
    debouncedFlush.cancel()
  }

  function upsertJobDebounced(patch) {
    const jobId = patch?.job_id || patch?.id || patch?.agent_id
    const agentId = patch?.agent_id

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

    const cleanPatch = Object.fromEntries(
      Object.entries(patch || {}).filter(([_, v]) => v !== undefined)
    )

    const existing = pendingUpdates.get(uniqueKey)
    if (existing) {
      pendingUpdates.set(uniqueKey, { ...existing, ...cleanPatch })
    } else {
      pendingUpdates.set(uniqueKey, { ...cleanPatch })
    }

    debouncedFlush()
  }

  function flushPendingForJob(uniqueKey) {
    if (!uniqueKey || !pendingUpdates.has(uniqueKey)) return
    const patch = pendingUpdates.get(uniqueKey)
    pendingUpdates.delete(uniqueKey)
    upsertJob(patch)
  }


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
      upsertJob({
        ...previous,
        messages_waiting_count: count,
        action_required_unread: actionRequiredCount,
      })
    }
  }

  const debouncedFetchWaitingCounts = debounce(fetchWaitingCounts, 500, { maxWait: 3000 })

  function refreshMessagesWaitingCounts(projectId) {
    if (!projectId) return
    debouncedFetchWaitingCounts(projectId)
  }

  function removeJob(uniqueKeyOrJobId) {
    if (!uniqueKeyOrJobId) return
    if (jobsById.value.has(uniqueKeyOrJobId)) {
      jobsById.value = createNextMapWithout(jobsById.value, uniqueKeyOrJobId)
      return
    }
    for (const [key, job] of jobsById.value.entries()) {
      if (job.job_id === uniqueKeyOrJobId) {
        jobsById.value = createNextMapWithout(jobsById.value, key)
        return
      }
    }
  }



  const missionTopUpInFlight = new Set()
  const missionTopUpQueued = new Set()

  async function topUpMission(jobId) {
    if (!jobId) return

    if (missionTopUpInFlight.has(jobId)) {
      missionTopUpQueued.add(jobId)
      return
    }
    missionTopUpInFlight.add(jobId)

    try {
      const response = await api.agentJobs.get(jobId)
      const mission = response?.data?.mission
      if (typeof mission === 'string') {
        const key = resolveJobId(jobId)
        const previous = key ? jobsById.value.get(key) : null
        if (previous) {
          upsertJob({
            ...previous,
            mission,
            mission_truncated: false,
            mission_length: mission.length,
          })
        }
      }
    } catch (error) {
      // eslint-disable-next-line no-console
      console.debug('[agentJobsStore] mission top-up failed (non-fatal):', error)
    } finally {
      missionTopUpInFlight.delete(jobId)
      if (missionTopUpQueued.delete(jobId)) {
        topUpMission(jobId)
      }
    }
  }

  function maybeTopUpMission(payload) {
    if (!payload?.mission_truncated) return
    topUpMission(payload.job_id || payload.agent_id || payload.id)
  }

  function handleCreated(payload) {
    upsertJob(payload)
    maybeTopUpMission(payload)
  }

  function handleUpdated(payload) {
    upsertJob(payload)
    maybeTopUpMission(payload)
  }

  function handleStatusChanged(payload) {
    const existingKey = resolveJobId(payload?.job_id) || resolveJobId(payload?.agent_id)
    if (!existingKey) {
      // eslint-disable-next-line no-console
      console.debug('[handleStatusChanged] Ignoring status for unknown job:', payload?.job_id)
      return
    }

    flushPendingForJob(existingKey)

    upsertJob(payload)
  }

  function handleMissionLengthUpdated(payload) {
    const existingKey = resolveJobId(payload?.job_id)
    if (!existingKey) return
    upsertJob({ job_id: payload.job_id, mission_length: payload.mission_length })
  }

  function handleProgressUpdate(payload) {
    if (!payload?.job_id) return

    const updates = {
      job_id: payload.job_id,
      progress: payload.progress,
      current_task: payload.current_task,
      last_progress_at: payload.last_progress_at,
    }

    if (payload.agent_display_name) {
      updates.agent_display_name = payload.agent_display_name
    }
    if (payload.agent_name) {
      updates.agent_name = payload.agent_name
    }
    if (payload.agent_id) {
      updates.agent_id = payload.agent_id
    }

    if (payload.todo_steps) {
      updates.job_metadata = { todo_steps: payload.todo_steps }

      if (Array.isArray(payload.todo_steps)) {
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
        const total = payload.todo_steps.total_steps
        const completed = payload.todo_steps.completed_steps
        const skipped = payload.todo_steps.skipped_steps || 0
        if (typeof total === 'number' && typeof completed === 'number') {
          updates.steps = { completed, skipped, total }
        }
      }
    }

    if (payload.todo_items && Array.isArray(payload.todo_items)) {
      updates.todo_items = payload.todo_items
    }

    upsertJobDebounced(updates)
  }

  function resolveJobId(identifier) {
    if (!identifier) return null

    if (jobsById.value.has(identifier)) {
      return identifier
    }

    for (const job of jobsById.value.values()) {
      if (job.agent_id === identifier) {
        return job.unique_key
      }
    }

    for (const job of jobsById.value.values()) {
      if (job.job_id === identifier) {
        return job.unique_key
      }
    }

    for (const job of jobsById.value.values()) {
      if (job.agent_display_name === identifier || job.agent_name === identifier) {
        return job.unique_key
      }
    }

    return null
  }

  function $reset() {
    jobsById.value = new Map()
    discardPendingUpdates()
    debouncedFetchWaitingCounts.cancel()
  }

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
    jobsById: jobsByIdProxy,

    jobs,
    sortedJobs,
    jobCount,

    getJob,
    resolveJobId,

    setJobs,
    upsertJob,
    removeJob,
    refreshMessagesWaitingCounts,
    topUpMission,

    handleCreated,
    handleUpdated,
    handleStatusChanged,
    handleMissionLengthUpdated,
    handleProgressUpdate,

    flushPendingUpdates,

    $reset,
  }
})
