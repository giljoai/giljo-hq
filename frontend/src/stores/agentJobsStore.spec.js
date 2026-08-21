/**
 * agentJobsStore.spec.js — TSK-9372
 *
 * $reset coverage: after mutating state, every exposed state field returns to
 * its initial value. $reset clears state between sessions and on logout; a
 * silently broken one leaks a previous session's jobs into the next view.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAgentJobsStore } from './agentJobsStore'

describe('agentJobsStore — $reset (TSK-9372)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useAgentJobsStore()
  })

  it('$reset clears all state', () => {
    store.setJobs([
      { job_id: 'job-1', agent_id: 'agent-1', status: 'working', agent_display_name: 'implementer' },
      { job_id: 'job-2', agent_id: 'agent-2', status: 'complete', agent_display_name: 'tester' },
    ])
    store.upsertJob({ job_id: 'job-3', agent_id: 'agent-3', status: 'spawned' })
    expect(store.jobCount).toBe(3)

    store.$reset()

    expect(store.jobsById.value.size).toBe(0)
    expect(store.jobCount).toBe(0)
    expect(store.jobs).toHaveLength(0)
    expect(store.sortedJobs).toHaveLength(0)
    expect(store.getJob('job-1')).toBeNull()
    expect(store.resolveJobId('agent-1')).toBeNull()
  })
})

/**
 * FE-9380 — $reset must also drop the module-closure debounce queue.
 *
 * pendingUpdates and debouncedFlush live in the store's closure, not in exposed
 * state, so the coverage above passes even when a patch queued before logout is
 * still in flight. Up to 300ms after $reset the flush fires and upsertJob
 * re-inserts the previous session's job into the fresh Map.
 */
describe('agentJobsStore — $reset cancels in-flight debounced updates (FE-9380)', () => {
  let store

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    store = useAgentJobsStore()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('a progress update queued before $reset does not re-insert the job', () => {
    store.setJobs([
      { job_id: 'job-1', agent_id: 'agent-1', status: 'working', agent_display_name: 'implementer', progress: 10 },
    ])

    // Queue a debounced patch, then log out before the 300ms window elapses.
    store.handleProgressUpdate({
      job_id: 'job-1',
      agent_id: 'agent-1',
      progress: 90,
      current_task: 'Writing tests',
      last_progress_at: '2026-08-08T10:00:00Z',
    })
    expect(store.jobCount).toBe(1)

    store.$reset()
    expect(store.jobCount).toBe(0)

    // Well past the debounce window: the queue must be gone, not merely late.
    vi.advanceTimersByTime(1000)

    expect(store.jobCount).toBe(0)
    expect(store.jobsById.value.size).toBe(0)
    expect(store.getJob('agent-1')).toBeNull()
    expect(store.getJob('job-1')).toBeNull()
  })

  it('$reset empties the queue so a later explicit flush cannot resurrect it', () => {
    store.setJobs([{ job_id: 'job-1', agent_id: 'agent-1', status: 'working' }])
    store.handleProgressUpdate({ job_id: 'job-1', agent_id: 'agent-1', progress: 90 })

    store.$reset()
    store.flushPendingUpdates()

    expect(store.jobCount).toBe(0)
    expect(store.getJob('agent-1')).toBeNull()
  })

  it('normal debounced flushing still works after a $reset', () => {
    store.$reset()

    store.setJobs([{ job_id: 'job-2', agent_id: 'agent-2', status: 'working', progress: 10 }])
    store.handleProgressUpdate({ job_id: 'job-2', agent_id: 'agent-2', progress: 55 })

    expect(store.getJob('agent-2').progress).toBe(10)
    vi.advanceTimersByTime(300)
    expect(store.getJob('agent-2').progress).toBe(55)
  })

  /**
   * The project-switch variant: a switch never calls $reset at all. loadJobs(B)
   * awaits a fetch and then replaces the Map via setJobs; if those awaits resolve
   * inside the debounce window, a project-A patch flushes AFTER the replace and
   * inserts a row into project B's Map. JobsTab's BE-6229 filter drops such a row
   * (the progress payload carries no project_id) but LaunchTab renders sortedJobs
   * unfiltered, so it would show. An authoritative REST replace supersedes any
   * queued delta -- the delta is stale against the snapshot by definition.
   */
  it('a patch queued for the previous project does not survive a setJobs replace', () => {
    store.setJobs([
      { job_id: 'job-a', agent_id: 'agent-a', project_id: 'project-a', status: 'working', progress: 10 },
    ])
    store.handleProgressUpdate({ job_id: 'job-a', agent_id: 'agent-a', progress: 70 })

    // Switch: the project-B REST reload lands before the 300ms window elapses.
    store.setJobs([
      { job_id: 'job-b', agent_id: 'agent-b', project_id: 'project-b', status: 'working', progress: 5 },
    ])

    vi.advanceTimersByTime(1000)

    expect(store.jobCount).toBe(1)
    expect(store.getJob('agent-b')).toBeTruthy()
    expect(store.getJob('agent-a')).toBeNull()
    // The ghost would carry no project_id, which is what makes it invisible to
    // JobsTab's filter and visible in LaunchTab's unfiltered list.
    expect(store.jobs.every((job) => job.project_id === 'project-b')).toBe(true)
  })
})
