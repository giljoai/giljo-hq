/**
 * Characterization of how agentJobsStore finds the existing row for a patch,
 * for the immediate path (upsertJob) and the debounced path (progress
 * updates): execution_id, then unique_key, then agent_id, then job_id; a
 * patch that matches nothing becomes a new row.
 *
 * Edition Scope: CE
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentJobsStore } from '@/stores/agentJobsStore'

const keys = (store) => Array.from(store.jobsById.keys())
const row = (store, key) => store.jobsById.get(key)

describe('agentJobsStore key resolution', () => {
  let store
  beforeEach(() => {
    setActivePinia(createPinia())
    store = useAgentJobsStore()
    store.upsertJob({ job_id: 'job-1', agent_id: 'agent-1', execution_id: 'exec-1', status: 'waiting' })
  })

  it('seeds one row keyed by agent_id', () => {
    expect(keys(store)).toEqual(['agent-1'])
  })

  it.each([
    ['execution_id', { execution_id: 'agent-1', job_id: 'other' }],
    ['unique_key', { unique_key: 'agent-1', job_id: 'other' }],
    ['agent_id', { agent_id: 'agent-1', job_id: 'other' }],
    ['job_id', { job_id: 'job-1' }],
  ])('upsertJob finds the row by %s', (_by, patch) => {
    store.upsertJob({ ...patch, status: 'working' })
    expect(keys(store)).toEqual(['agent-1'])
    expect(row(store, 'agent-1').status).toBe('working')
  })

  it('upsertJob keeps existing fields when the patch carries undefined', () => {
    store.upsertJob({ job_id: 'job-1', status: undefined, progress: 3 })
    expect(row(store, 'agent-1').status).toBe('waiting')
    expect(row(store, 'agent-1').progress).toBe(3)
  })

  it('upsertJob adds a new row for an unknown job', () => {
    store.upsertJob({ job_id: 'job-2', status: 'waiting' })
    expect(keys(store)).toEqual(['agent-1', 'job-2'])
  })

  it('a progress update finds the row by job_id', () => {
    store.handleProgressUpdate({ job_id: 'job-1', progress: 50 })
    store.flushPendingUpdates()
    expect(keys(store)).toEqual(['agent-1'])
    expect(row(store, 'agent-1').progress).toBe(50)
  })

  it('a progress update finds the row by agent_id before job_id', () => {
    store.handleProgressUpdate({ job_id: 'job-x', agent_id: 'agent-1', progress: 10 })
    store.flushPendingUpdates()
    expect(keys(store)).toEqual(['agent-1'])
    expect(row(store, 'agent-1').progress).toBe(10)
  })

  it('queued progress updates for one job merge, undefined fields ignored', () => {
    store.handleProgressUpdate({ job_id: 'job-1', progress: 10, current_task: 'a' })
    store.handleProgressUpdate({ job_id: 'job-1', progress: 20 })
    expect(row(store, 'agent-1').progress).toBeUndefined()
    store.flushPendingUpdates()
    expect(row(store, 'agent-1').progress).toBe(20)
    expect(row(store, 'agent-1').current_task).toBe('a')
  })

  it('a progress update for an unknown job adds a row', () => {
    store.handleProgressUpdate({ job_id: 'job-new', progress: 5 })
    store.flushPendingUpdates()
    expect(keys(store)).toEqual(['agent-1', 'job-new'])
  })

  it('handleCreated and handleUpdated both upsert', () => {
    store.handleCreated({ job_id: 'job-2', status: 'waiting' })
    store.handleUpdated({ job_id: 'job-2', status: 'working' })
    expect(row(store, 'job-2').status).toBe('working')
  })
})
