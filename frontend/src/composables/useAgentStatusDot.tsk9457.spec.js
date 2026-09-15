import { describe, it, expect } from 'vitest'
import { agentStatusDot } from '@/composables/useAgentStatusDot'

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
    expect(dot.color).not.toBe('#666666')
  })

  it('silent stays SILENT once the payload carries it — the reported defect', () => {
    const fromCardList = { participant_id: 'agent-a', status: 'silent', last_seen_at: '2026-08-18T01:49:15Z' }
    const fromDirectory = { participant_id: 'agent-a', status: 'silent', last_seen_at: '2026-08-18T01:49:15Z' }

    expect(agentStatusDot(fromCardList).label).toBe('Silent')
    expect(agentStatusDot(fromDirectory).label).toBe(agentStatusDot(fromCardList).label)
  })

  it('a null status still reads as never-checked-in, never as healthy', () => {
    expect(agentStatusDot({ participant_id: 'ghost', status: null, last_seen_at: null }).label).toBe(
      'Never checked in'
    )
  })
})
