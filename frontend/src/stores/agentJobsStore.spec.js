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

    expect(store.jobsById.size).toBe(0)
    expect(store.jobCount).toBe(0)
    expect(store.jobs).toHaveLength(0)
    expect(store.sortedJobs).toHaveLength(0)
    expect(store.getJob('job-1')).toBeNull()
    expect(store.resolveJobId('agent-1')).toBeNull()
  })
})

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

    vi.advanceTimersByTime(1000)

    expect(store.jobCount).toBe(0)
    expect(store.jobsById.size).toBe(0)
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

  it('a patch queued for the previous project does not survive a setJobs replace', () => {
    store.setJobs([
      { job_id: 'job-a', agent_id: 'agent-a', project_id: 'project-a', status: 'working', progress: 10 },
    ])
    store.handleProgressUpdate({ job_id: 'job-a', agent_id: 'agent-a', progress: 70 })

    store.setJobs([
      { job_id: 'job-b', agent_id: 'agent-b', project_id: 'project-b', status: 'working', progress: 5 },
    ])

    vi.advanceTimersByTime(1000)

    expect(store.jobCount).toBe(1)
    expect(store.getJob('agent-b')).toBeTruthy()
    expect(store.getJob('agent-a')).toBeNull()
    expect(store.jobs.every((job) => job.project_id === 'project-b')).toBe(true)
  })
})
