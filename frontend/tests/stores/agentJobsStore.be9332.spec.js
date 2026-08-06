/**
 * BE-9332 - a CLI-driven staging must produce the orchestrator card.
 *
 * The backend half of BE-9332 makes the MCP `stage_project` tool emit
 * `orchestrator:prompt_generated` (it previously emitted nothing, so staging from a
 * headless/CLI agent session left the dashboard silent).
 *
 * This closes the "the card appears" half of the DoD at the STORE layer: it drives the
 * REAL route definition from agentEventRoutes.js with the EXACT payload shape the new
 * shared emitter puts on the wire
 * (src/giljo_mcp/services/orchestrator_prompt_ws_broadcast.py) and asserts an
 * orchestrator row materialises with all four identity fields on it.
 *
 * NOTE on execution_id: an earlier research pass claimed omitting it would leave a
 * duplicate "ghost card" behind after a refetch. That was checked here and is NOT true —
 * normalizeJob derives unique_key as `agent_id || execution_id || job_id` (agent_id
 * first, and the payload always carries agent_id), and setJobs builds a brand-new Map
 * and replaces the old one wholesale, so a refetch cannot strand a duplicate. The real
 * reason execution_id must be on the payload is narrower and verifiable: both REST
 * prompt endpoints already send it, the route reads it onto the row, and leaving it out
 * of the MCP payload would reintroduce the cross-site drift this change exists to end.
 *
 * Edition Scope: CE
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAgentJobsStore } from '@/stores/agentJobsStore'
import { AGENT_EVENT_ROUTES } from '@/stores/eventRoutes/agentEventRoutes'

// Exactly what broadcast_orchestrator_prompt_generated() sends for the MCP staging
// path: the three always-present keys plus agent_id / execution_id / tool.
const EMITTED_PAYLOAD = {
  project_id: 'proj-9332',
  orchestrator_id: 'orch-9332',
  agent_id: 'agent-9332',
  execution_id: 'exec-9332',
  tool: 'claude-code',
  thin_client: true,
}

describe('BE-9332 - orchestrator:prompt_generated renders the orchestrator card', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useAgentJobsStore()
  })

  it('is a routed event (an unrouted event would be silently dropped)', () => {
    expect(AGENT_EVENT_ROUTES['orchestrator:prompt_generated']).toBeTruthy()
    expect(typeof AGENT_EVENT_ROUTES['orchestrator:prompt_generated'].handler).toBe('function')
  })

  it('creates the orchestrator row from an empty store (the CLI-driven staging case)', async () => {
    expect(store.jobs.length).toBe(0)

    await AGENT_EVENT_ROUTES['orchestrator:prompt_generated'].handler(EMITTED_PAYLOAD)

    expect(store.jobs.length).toBe(1)
    const job = store.jobs[0]
    expect(job.job_id).toBe('orch-9332')
    expect(job.agent_id).toBe('agent-9332')
    expect(job.execution_id).toBe('exec-9332')
    expect(job.project_id).toBe('proj-9332')
    expect(job.agent_display_name).toBe('orchestrator')
    expect(job.status).toBe('waiting')
  })

  it('reconciles with the persisted row on a project refetch (no duplicate)', async () => {
    await AGENT_EVENT_ROUTES['orchestrator:prompt_generated'].handler(EMITTED_PAYLOAD)
    expect(store.jobs.length).toBe(1)

    // The project refetch (useAgentJobs.loadJobs -> GET /api/agent-jobs/ -> setJobs)
    // returns the SAME orchestrator as a persisted row. The live card and the persisted
    // row must reconcile to ONE entry — they agree on agent_id, which is what
    // normalizeJob derives unique_key from.
    store.setJobs([
      {
        job_id: 'orch-9332',
        agent_id: 'agent-9332',
        execution_id: 'exec-9332',
        project_id: 'proj-9332',
        agent_display_name: 'orchestrator',
        status: 'waiting',
      },
    ])

    expect(store.jobs.length).toBe(1)
    expect(store.jobs[0].execution_id).toBe('exec-9332')
  })

  it('a subsequent agent:status_changed reaches the row the event created', async () => {
    // The compounding failure this fix removes: with no creating event,
    // handleStatusChanged refuses to create a row, so every later status update for
    // that orchestrator was silently dropped and the card never appeared at all.
    await AGENT_EVENT_ROUTES['orchestrator:prompt_generated'].handler(EMITTED_PAYLOAD)

    store.handleStatusChanged({ job_id: 'orch-9332', status: 'working' })

    expect(store.jobs.length).toBe(1)
    expect(store.jobs[0].status).toBe('working')
  })
})
