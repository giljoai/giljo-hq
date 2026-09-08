/**
 * jobsSectionLabel.spec.js — FE-9525d
 *
 * Pure unit tests for the plural Jobs viewport's section label helper. No
 * Vue / store imports — pure function tests only.
 *
 * Edition scope: Both.
 */
import { describe, it, expect } from 'vitest'
import { jobsSectionLabelFor, isReadyForReview, JOBS_SECTION_LABELS } from './jobsSectionLabel'

describe('jobsSectionLabelFor', () => {
  it('returns Staged when implementation has not been launched', () => {
    expect(jobsSectionLabelFor({ staging_status: 'staging_complete', implementation_launched_at: null })).toBe(
      JOBS_SECTION_LABELS.STAGED,
    )
  })

  // FE-9551: a project with no lifecycle fields at all has never entered
  // staging -- it is Activated, not Staged. The pre-fix catch-all wrongly
  // called this Staged.
  it('returns Activated for a project with no lifecycle fields at all', () => {
    expect(jobsSectionLabelFor({})).toBe(JOBS_SECTION_LABELS.ACTIVATED)
  })

  // FE-9551 red-first: staging_status null/undefined + never launched is the
  // real "Activated" floor -- the state the pre-fix catch-all mislabeled
  // "Staged" because it wasn't derived off the actual staging_status field.
  it('returns Activated when staging_status is null and implementation has not launched', () => {
    expect(
      jobsSectionLabelFor({ staging_status: null, implementation_launched_at: null }, []),
    ).toBe(JOBS_SECTION_LABELS.ACTIVATED)
  })

  // FE-9551: staging_status 'staging' means staging is actively in progress --
  // Planning, reusing the exact word statusConfig.js already uses for this
  // server value at the agent-row level.
  it('returns Planning when staging_status is "staging"', () => {
    expect(
      jobsSectionLabelFor({ staging_status: 'staging', implementation_launched_at: null }, []),
    ).toBe(JOBS_SECTION_LABELS.PLANNING)
  })

  // FE-9551: pin Staged explicitly against the real staging_status field
  // (not just "implementation not launched") now that Staged has a precise
  // meaning of its own in the ladder.
  it('returns Staged when staging_status is "staging_complete" and implementation has not launched', () => {
    expect(
      jobsSectionLabelFor({ staging_status: 'staging_complete', implementation_launched_at: null }, []),
    ).toBe(JOBS_SECTION_LABELS.STAGED)
  })

  it('returns Implementing once implementation_launched_at is set', () => {
    expect(
      jobsSectionLabelFor({
        staging_status: 'staging_complete',
        implementation_launched_at: '2026-08-30T12:00:00Z',
      }),
    ).toBe(JOBS_SECTION_LABELS.IMPLEMENTING)
  })

  // FE-9551 overrides the "active" half of the
  // ruling 19 / D8 ban -- Activated is now a real label. "Claim" stays
  // banned; nothing in this vocabulary may resurrect that word.
  it('permits "Activated" but never returns "claim" (FE-9551 override of ruling 19 / D8)', () => {
    const labels = Object.values(JOBS_SECTION_LABELS)
    expect(labels).toContain('Activated')
    for (const label of labels) {
      expect(label.toLowerCase()).not.toContain('claim')
    }
  })

  // D8's whiteboard: NEEDS INPUT takes precedence in the ASCII mock's own
  // "orch: cc-2 / ▶ tester" card, which is mid-implementation yet labeled
  // Needs Input, not Implementing.
  it('returns Needs Input when any agent is blocked, even mid-implementation', () => {
    const label = jobsSectionLabelFor(
      { implementation_launched_at: '2026-08-30T12:00:00Z' },
      [{ status: 'working' }, { status: 'blocked' }],
    )
    expect(label).toBe(JOBS_SECTION_LABELS.NEEDS_INPUT)
  })

  it('returns Needs Input when any agent is silent', () => {
    const label = jobsSectionLabelFor(
      { implementation_launched_at: '2026-08-30T12:00:00Z' },
      [{ status: 'silent' }],
    )
    expect(label).toBe(JOBS_SECTION_LABELS.NEEDS_INPUT)
  })

  it('ignores agents entirely when none is blocked or silent', () => {
    const label = jobsSectionLabelFor(
      { implementation_launched_at: '2026-08-30T12:00:00Z' },
      [{ status: 'working' }, { status: 'complete' }],
    )
    expect(label).toBe(JOBS_SECTION_LABELS.IMPLEMENTING)
  })

  it('defaults to an empty agent list without throwing', () => {
    expect(jobsSectionLabelFor({ implementation_launched_at: null })).toBe(JOBS_SECTION_LABELS.ACTIVATED)
  })

  // FE-9548: the mock's fourth board state -- every agent (including the
  // orchestrator) has reached a terminal status, so the project sits in
  // Review until the operator actually closes it out.
  it('returns Review when every agent, including the orchestrator, is terminal', () => {
    const label = jobsSectionLabelFor(
      { status: 'active', implementation_launched_at: '2026-08-30T12:00:00Z' },
      [
        { agent_display_name: 'orchestrator', status: 'closed' },
        { agent_display_name: 'implementer', status: 'complete' },
      ],
    )
    expect(label).toBe(JOBS_SECTION_LABELS.REVIEW)
  })

  it('does not return Review while any agent is still non-terminal', () => {
    const label = jobsSectionLabelFor(
      { status: 'active', implementation_launched_at: '2026-08-30T12:00:00Z' },
      [
        { agent_display_name: 'orchestrator', status: 'working' },
        { agent_display_name: 'implementer', status: 'complete' },
      ],
    )
    expect(label).toBe(JOBS_SECTION_LABELS.IMPLEMENTING)
  })
})

describe('isReadyForReview', () => {
  it('is false once the project itself is already completed/terminated/cancelled', () => {
    const agents = [
      { agent_display_name: 'orchestrator', status: 'closed' },
      { agent_display_name: 'implementer', status: 'complete' },
    ]
    expect(isReadyForReview({ status: 'completed' }, agents)).toBe(false)
    expect(isReadyForReview({ status: 'terminated' }, agents)).toBe(false)
    expect(isReadyForReview({ status: 'cancelled' }, agents)).toBe(false)
  })

  it('is false for a staged project that has not launched implementation yet', () => {
    const agents = [{ agent_display_name: 'orchestrator', status: 'closed' }]
    expect(
      isReadyForReview({ status: 'active', staging_status: 'staging_complete', implementation_launched_at: null }, agents),
    ).toBe(false)
  })

  it('is false with no agents at all', () => {
    expect(isReadyForReview({ status: 'active' }, [])).toBe(false)
  })

  it('is false when the orchestrator is not terminal even if specialists are', () => {
    const agents = [
      { agent_display_name: 'orchestrator', status: 'working' },
      { agent_display_name: 'implementer', status: 'complete' },
    ]
    expect(isReadyForReview({ status: 'active' }, agents)).toBe(false)
  })

  it('is true when every agent including the orchestrator is terminal', () => {
    const agents = [
      { agent_display_name: 'orchestrator', status: 'closed' },
      { agent_display_name: 'implementer', status: 'complete' },
      { agent_display_name: 'tester', status: 'decommissioned' },
    ]
    expect(isReadyForReview({ status: 'active' }, agents)).toBe(true)
  })

  // FE-9548 regression: the orchestrator must be
  // found via the CANONICAL isOrchestrator predicate (agent_name OR
  // agent_display_name), not a narrower agent_display_name-only check. An
  // orchestrator identified by agent_name with a different/absent
  // agent_display_name must still be recognized -- failed on the
  // agent_display_name-only implementation, passes after importing
  // isOrchestrator from utils/agentDisplay.
  it('recognizes the orchestrator via agent_name even when agent_display_name differs', () => {
    const agents = [
      { agent_name: 'orchestrator', agent_display_name: 'Orchestrator (Phase 5)', status: 'closed' },
      { agent_display_name: 'implementer', status: 'complete' },
    ]
    expect(isReadyForReview({ status: 'active' }, agents)).toBe(true)
  })
})
