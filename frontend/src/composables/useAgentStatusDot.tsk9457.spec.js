/**
 * TSK-9457 — every status the server can serve must have a display path.
 *
 * The fix put `agent_executions.status` on the thread-participant payload, so the Hub's
 * agent pills now render every value that column can legally hold. `getStatusLabel`
 * degrades an unmapped status to the string "Unknown" and `getStatusColor` to a muted
 * grey — silently, and only on screen. That is the house rule this file enforces: a
 * store status with no display-map entry renders raw.
 *
 * The list below is the `ck_agent_execution_status` CHECK constraint in
 * `src/giljo_mcp/models/agent_identity.py`, verbatim. Adding a status there without
 * adding it to `statusConfig.js` (or to `UNMAPPED_TO_IDLE`, which is how `staged` is
 * handled deliberately — see the composable's own note on why it does NOT get its own
 * colour) fails here rather than shipping "Unknown" to the operator.
 */
import { describe, it, expect } from 'vitest'
import { agentStatusDot } from '@/composables/useAgentStatusDot'

// ck_agent_execution_status, src/giljo_mcp/models/agent_identity.py
const ADMISSIBLE_STATUSES = [
  'waiting',
  'working',
  'blocked',
  'complete',
  'closed',
  'silent',
  'decommissioned',
  'idle',
  'sleeping',
  'awaiting_user',
  'staged',
]

describe('TSK-9457: the participant payload cannot render a raw status', () => {
  it.each(ADMISSIBLE_STATUSES)('%s has a real label and colour', (status) => {
    const dot = agentStatusDot({ participant_id: 'agent-a', status, last_seen_at: '2026-08-18T01:49:15Z' })
    expect(dot.label).not.toBe('Unknown')
    expect(dot.label).toBeTruthy()
    expect(dot.color).not.toBe('#666666') // STATUS_COLORS.FALLBACK
  })

  it('silent stays SILENT once the payload carries it — the reported defect', () => {
    // Before the fix, list_participants served no `status` key. An absent status with a
    // present last_seen_at normalises to `idle`, which is labelled "Monitoring": the
    // operator saw "Silent" on the card and "Monitoring" inside it, for one agent.
    const fromCardList = { participant_id: 'agent-a', status: 'silent', last_seen_at: '2026-08-18T01:49:15Z' }
    const fromDirectory = { participant_id: 'agent-a', status: 'silent', last_seen_at: '2026-08-18T01:49:15Z' }

    expect(agentStatusDot(fromCardList).label).toBe('Silent')
    expect(agentStatusDot(fromDirectory).label).toBe(agentStatusDot(fromCardList).label)
  })

  it('a null status still reads as never-checked-in, never as healthy', () => {
    // The payload now always CARRIES `status`; null means "no execution registered".
    // Serving null rather than coalescing a default is what keeps this honest.
    expect(agentStatusDot({ participant_id: 'ghost', status: null, last_seen_at: null }).label).toBe(
      'Never checked in'
    )
  })
})
