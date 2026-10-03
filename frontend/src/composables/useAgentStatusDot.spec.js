
import { describe, it, expect } from 'vitest'
import { agentStatusDot, agentPillTitle, agentStatusMeaning } from '@/composables/useAgentStatusDot'
import { getStatusColor, getStatusLabel } from '@/utils/statusConfig'

const IDLE_SLATE = '#7a9bb5'

describe('agentStatusDot', () => {
  it('takes its colour and label from statusConfig, never from a local map', () => {
    for (const status of ['waiting', 'working', 'blocked', 'complete', 'sleeping', 'closed']) {
      const dot = agentStatusDot({ status, last_seen_at: '2026-08-04T12:00:00Z' })
      expect(dot.color).toBe(getStatusColor(status))
      expect(dot.label).toBe(getStatusLabel(status))
    }
  })

  it('renders awaiting_user in the decision amber the Jobs board uses', () => {
    const dot = agentStatusDot({ status: 'awaiting_user', last_seen_at: '2026-08-04T12:00:00Z' })
    expect(dot.color).toBe('#ffc107')
  })

  it('falls back to idle slate when the status is missing — NEVER to green', () => {
    const dot = agentStatusDot({ status: null, last_seen_at: '2026-08-04T12:00:00Z' })
    expect(dot.color).toBe(IDLE_SLATE)
    expect(dot.color).not.toBe(getStatusColor('complete'))
    expect(dot.label).not.toBe('Unknown')
  })

  it('reads staged as idle rather than rendering "Unknown"', () => {
    const dot = agentStatusDot({ status: 'staged', last_seen_at: '2026-08-04T12:00:00Z' })
    expect(dot.color).toBe(IDLE_SLATE)
    expect(dot.label).not.toBe('Unknown')
  })

  it('gives a never-registered agent a hollow ring, not a filled dot', () => {
    const dot = agentStatusDot({ status: null, last_seen_at: null })
    expect(dot.color).toBe('transparent')
    expect(dot.ring).toContain('inset')
    expect(dot.label).toBe('Never checked in')
  })

  it('treats a missing participant as never-registered rather than throwing', () => {
    expect(agentStatusDot(undefined).label).toBe('Never checked in')
  })
})

describe('agentPillTitle', () => {
  it('names the agent, its harness and its status — the pill dropped all three visually', () => {
    const title = agentPillTitle(
      { display_name: 'LANE_A — installer + harness fixes', status: 'working', last_seen_at: 'x' },
      'Claude Code',
    )
    expect(title).toBe(
      'LANE_A — installer + harness fixes · Claude Code · Working: actively running in its harness',
    )
  })

  it('falls back to the participant id when there is no display name', () => {
    expect(agentPillTitle({ participant_id: 'lane-b', status: 'idle', last_seen_at: 'x' }, 'Codex')).toContain('lane-b')
  })

  it('explains what the state means, not just what the enum calls it', () => {
    const title = agentPillTitle({ participant_id: 'a', status: 'blocked', last_seen_at: 'x' }, 'Codex')
    expect(title).toContain('Blocked: stuck on something it cannot decide')
  })

  it('explains a terse Jobs-board label — "Monitoring" alone does not tell an operator anything', () => {
    expect(agentStatusMeaning({ status: 'idle', last_seen_at: 'x' })).toBe(
      'registered, watching, not working',
    )
    expect(agentStatusMeaning({ status: null, last_seen_at: 'x' })).toBe(
      'registered, watching, not working',
    )
  })

  it('adds no meaning to a never-registered agent — its label already says all we know', () => {
    expect(agentStatusMeaning({ status: null, last_seen_at: null })).toBe('')
    expect(agentPillTitle({ participant_id: 'ghost', last_seen_at: null }, 'Codex')).toBe(
      'ghost · Codex · Never checked in',
    )
  })
})
