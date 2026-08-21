/**
 * agentJobsStore — BE-9416, the consumer half.
 *
 * An agent mission cannot ride the cross-worker broker whole: pg_notify caps a
 * payload at 7999 bytes, so agent:created and agent:mission_updated now send a
 * bounded excerpt plus `mission_truncated` / `mission_length`. Two components read
 * the mission straight off the store row — AgentJobModal renders it, and
 * AgentMissionEditModal SEEDS AN EDITOR from it — so without the top-up the
 * operator would read (and, worse, be able to save back) a fragment.
 *
 * What is pinned here:
 *  - a truncated mission on agent:created is topped up to its full text
 *  - the same on agent:mission_updated (the repair path)
 *  - an ordinary mission fetches nothing at all
 *  - a burst coalesces into two reads and strands nobody on its excerpt
 *  - a top-up never CREATES a row (ghost-row guard, Handover 0463)
 *  - a failed top-up leaves the excerpt readable rather than blanking it
 *
 * Edition Scope: Both
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/api', () => ({
  default: {
    agentJobs: {
      get: vi.fn(),
      list: vi.fn(),
    },
  },
}))

import api from '@/services/api'
import { useAgentJobsStore } from '@/stores/agentJobsStore'

const JOB_ID = 'job-be9416'
const AGENT_ID = 'agent-be9416'
const EXCERPT = 'the first five kilobytes of a very long orchestrator mission'
const FULL_MISSION = `${EXCERPT} ... and the forty-five kilobytes the broker could not carry`

function truncatedEvent(overrides = {}) {
  return {
    job_id: JOB_ID,
    agent_id: AGENT_ID,
    execution_id: 'exec-be9416',
    project_id: 'proj-be9416',
    agent_display_name: 'orchestrator',
    agent_name: 'orchestrator',
    status: 'waiting',
    mission: EXCERPT,
    mission_truncated: true,
    mission_length: FULL_MISSION.length,
    ...overrides,
  }
}

/** A deferred promise so a test can control when the in-flight read resolves. */
function deferred() {
  let resolve
  const promise = new Promise((r) => {
    resolve = r
  })
  return { promise, resolve }
}

function jobPayload(mission = FULL_MISSION) {
  return { data: { job_id: JOB_ID, agent_id: AGENT_ID, mission } }
}

async function flush() {
  // Two microtask turns: one for the awaited request, one for the finally block
  // that drains the coalesced follow-up.
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('agentJobsStore — BE-9416 mission top-up', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useAgentJobsStore()
    vi.clearAllMocks()
    api.agentJobs.get.mockResolvedValue(jobPayload())
  })

  it('tops a truncated agent:created mission up to its full text', async () => {
    store.handleCreated(truncatedEvent())

    // Before the read resolves the row still holds the excerpt — that is the
    // window AgentMissionEditModal must refuse to seed from.
    expect(store.getJob(store.resolveJobId(JOB_ID)).mission).toBe(EXCERPT)

    await flush()

    const job = store.getJob(store.resolveJobId(JOB_ID))
    expect(api.agentJobs.get).toHaveBeenCalledWith(JOB_ID)
    expect(job.mission).toBe(FULL_MISSION)
    expect(job.mission_truncated).toBe(false)
    expect(job.mission_length).toBe(FULL_MISSION.length)
  })

  it('tops up on agent:mission_updated too — the repair path', async () => {
    store.setJobs([{ job_id: JOB_ID, agent_id: AGENT_ID, agent_display_name: 'orchestrator', status: 'working' }])

    store.handleUpdated(truncatedEvent({ status: 'working' }))
    await flush()

    expect(api.agentJobs.get).toHaveBeenCalledWith(JOB_ID)
    expect(store.getJob(store.resolveJobId(JOB_ID)).mission).toBe(FULL_MISSION)
  })

  it('fetches nothing for an ordinary mission that travelled whole', async () => {
    store.handleCreated(truncatedEvent({ mission: 'a short mission', mission_truncated: false, mission_length: 15 }))
    await flush()

    expect(api.agentJobs.get).not.toHaveBeenCalled()
    expect(store.getJob(store.resolveJobId(JOB_ID)).mission).toBe('a short mission')
  })

  it('coalesces a burst into two reads and strands nobody on an excerpt', async () => {
    // The load-bearing case. A read already in flight may have queried the server
    // BEFORE a newer edit committed, so merely skipping the second request could
    // leave the row stuck on its excerpt for good. A plain skip-if-busy passes the
    // call-count assertion and fails the content one.
    const first = deferred()
    api.agentJobs.get.mockReturnValueOnce(first.promise)

    store.handleCreated(truncatedEvent())
    // Four more events arrive while that first read is still open.
    for (let i = 0; i < 4; i += 1) {
      store.handleUpdated(truncatedEvent({ mission: `${EXCERPT} v${i}` }))
    }
    expect(api.agentJobs.get).toHaveBeenCalledTimes(1)

    const LATEST = `${FULL_MISSION} (latest)`
    api.agentJobs.get.mockResolvedValue(jobPayload(LATEST))
    first.resolve(jobPayload())
    await flush()

    expect(api.agentJobs.get).toHaveBeenCalledTimes(2)
    expect(store.getJob(store.resolveJobId(JOB_ID)).mission).toBe(LATEST)
  })

  it('never creates a row — a top-up answering a filtered event must not smuggle a ghost in', async () => {
    // Handover 0463: cross-project events are dropped by the router, but a fetch
    // answering one must not re-introduce the row the filter just refused.
    await store.topUpMission('job-that-is-not-in-the-store')

    expect(store.jobCount).toBe(0)
  })

  it('leaves the excerpt readable when the top-up fails', async () => {
    api.agentJobs.get.mockRejectedValue(new Error('network down'))

    store.handleCreated(truncatedEvent())
    await flush()

    const job = store.getJob(store.resolveJobId(JOB_ID))
    expect(job.mission).toBe(EXCERPT)
    // Still flagged, so a later event (or the modal) still knows not to trust it
    // as the whole mission.
    expect(job.mission_truncated).toBe(true)
  })

  it('does not write any store-wide loading or error state', async () => {
    // A background read nobody asked for must not raise a banner or a spinner
    // over a mission the operator can already partly read.
    store.handleCreated(truncatedEvent())
    await flush()

    expect(store.loading).toBeUndefined()
    expect(store.error).toBeUndefined()
  })
})
