/**
 * agentJobsStore — FE-9184 live Messages Waiting count refresh.
 *
 * refreshMessagesWaitingCounts(projectId) is the debounced live-update path
 * behind the jobs table's Messages Waiting badge: hub thread_message WS events
 * trigger it (via commHubEventRoutes), it refetches the project's /jobs rows
 * once per quiet window and patches ONLY messages_waiting_count onto jobs
 * already in the store — never creates rows (ghost-row guard, Handover 0463)
 * and never overwrites other fields with REST data.
 *
 * Edition Scope: CE
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/api', () => ({
  default: {
    agentJobs: {
      list: vi.fn(),
    },
  },
}))

import api from '@/services/api'
import { useAgentJobsStore } from '@/stores/agentJobsStore'

function seedJobs(store) {
  store.setJobs([
    {
      job_id: 'job-1',
      agent_id: 'agent-1',
      agent_display_name: 'implementer',
      agent_name: 'Implementer Agent',
      status: 'working',
      messages_waiting_count: 0,
    },
    {
      job_id: 'job-2',
      agent_id: 'agent-2',
      agent_display_name: 'tester',
      agent_name: 'Tester Agent',
      status: 'waiting',
      messages_waiting_count: 1,
    },
  ])
}

describe('agentJobsStore — FE-9184 refreshMessagesWaitingCounts', () => {
  let store

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    store = useAgentJobsStore()
    api.agentJobs.list.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('debounces a burst into a single fetch and patches counts onto existing jobs', async () => {
    seedJobs(store)
    api.agentJobs.list.mockResolvedValue({
      data: {
        jobs: [
          { job_id: 'job-1', agent_id: 'agent-1', messages_waiting_count: 3 },
          { job_id: 'job-2', agent_id: 'agent-2', messages_waiting_count: 0 },
        ],
      },
    })

    store.refreshMessagesWaitingCounts('project-1')
    store.refreshMessagesWaitingCounts('project-1')
    store.refreshMessagesWaitingCounts('project-1')

    // Debounced: nothing fires synchronously
    expect(api.agentJobs.list).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1000)

    expect(api.agentJobs.list).toHaveBeenCalledTimes(1)
    expect(api.agentJobs.list).toHaveBeenCalledWith('project-1')
    expect(store.getJob('agent-1').messages_waiting_count).toBe(3)
    expect(store.getJob('agent-2').messages_waiting_count).toBe(0)
  })

  it('patches only the count — other job fields survive a stale REST row', async () => {
    seedJobs(store)
    // REST row carries a DIFFERENT status than the store (stale vs a fresher
    // WS lifecycle event) — the count-only patch must not regress it.
    api.agentJobs.list.mockResolvedValue({
      data: {
        jobs: [
          { job_id: 'job-1', agent_id: 'agent-1', status: 'waiting', messages_waiting_count: 5 },
        ],
      },
    })

    store.refreshMessagesWaitingCounts('project-1')
    await vi.advanceTimersByTimeAsync(1000)

    const job = store.getJob('agent-1')
    expect(job.messages_waiting_count).toBe(5)
    expect(job.status).toBe('working')
    expect(job.agent_display_name).toBe('implementer')
  })

  it('never creates rows for jobs missing from the store', async () => {
    seedJobs(store)
    api.agentJobs.list.mockResolvedValue({
      data: {
        jobs: [
          { job_id: 'job-9', agent_id: 'agent-9', messages_waiting_count: 7 },
        ],
      },
    })

    store.refreshMessagesWaitingCounts('project-1')
    await vi.advanceTimersByTimeAsync(1000)

    expect(store.jobCount).toBe(2)
    expect(store.getJob('agent-9')).toBeNull()
  })

  it('does nothing without a projectId', async () => {
    seedJobs(store)

    store.refreshMessagesWaitingCounts('')
    store.refreshMessagesWaitingCounts(null)
    await vi.advanceTimersByTimeAsync(5000)

    expect(api.agentJobs.list).not.toHaveBeenCalled()
  })

  // FE-9380: the count refresh is a second module-closure debounce. A refresh
  // queued before logout must not fire its /jobs fetch for the session that
  // just ended.
  it('$reset cancels a pending count refresh before it fetches', async () => {
    seedJobs(store)
    api.agentJobs.list.mockResolvedValue({ data: { jobs: [] } })

    store.refreshMessagesWaitingCounts('project-1')
    store.$reset()

    await vi.advanceTimersByTimeAsync(5000)

    expect(api.agentJobs.list).not.toHaveBeenCalled()
    expect(store.jobCount).toBe(0)
  })

  it('count refreshes still work after a $reset', async () => {
    store.$reset()
    seedJobs(store)
    api.agentJobs.list.mockResolvedValue({
      data: { jobs: [{ job_id: 'job-1', agent_id: 'agent-1', messages_waiting_count: 4 }] },
    })

    store.refreshMessagesWaitingCounts('project-1')
    await vi.advanceTimersByTimeAsync(1000)

    expect(api.agentJobs.list).toHaveBeenCalledTimes(1)
    expect(store.getJob('agent-1').messages_waiting_count).toBe(4)
  })

  it('swallows a failed fetch without touching the store', async () => {
    seedJobs(store)
    api.agentJobs.list.mockRejectedValue(new Error('network down'))

    store.refreshMessagesWaitingCounts('project-1')
    await vi.advanceTimersByTimeAsync(1000)

    expect(api.agentJobs.list).toHaveBeenCalledTimes(1)
    expect(store.getJob('agent-1').messages_waiting_count).toBe(0)
    expect(store.getJob('agent-2').messages_waiting_count).toBe(1)
  })
})
