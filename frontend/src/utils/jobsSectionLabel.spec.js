import { jobsBoardLifecycleColor } from './jobsBoardLifecycle'
import { describe, it, expect } from 'vitest'
import { jobsSectionLabelFor, isReadyForReview, JOBS_SECTION_LABELS } from './jobsSectionLabel'

describe('jobsSectionLabelFor', () => {
  it('returns Staged when implementation has not been launched', () => {
    expect(jobsSectionLabelFor({ staging_status: 'staging_complete', implementation_launched_at: null })).toBe(
      JOBS_SECTION_LABELS.STAGED,
    )
  })

  it('returns Activated for a project with no lifecycle fields at all', () => {
    expect(jobsSectionLabelFor({})).toBe(JOBS_SECTION_LABELS.ACTIVATED)
  })

  it('returns Activated when staging_status is null and implementation has not launched', () => {
    expect(
      jobsSectionLabelFor({ staging_status: null, implementation_launched_at: null }, []),
    ).toBe(JOBS_SECTION_LABELS.ACTIVATED)
  })

  it('returns Planning when staging_status is "staging"', () => {
    expect(
      jobsSectionLabelFor({ staging_status: 'staging', implementation_launched_at: null }, []),
    ).toBe(JOBS_SECTION_LABELS.PLANNING)
  })

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

  it('permits "Activated" but never returns "claim" (FE-9551 override of ruling 19 / D8)', () => {
    const labels = Object.values(JOBS_SECTION_LABELS)
    expect(labels).toContain('Activated')
    for (const label of labels) {
      expect(label.toLowerCase()).not.toContain('claim')
    }
  })

  it('returns Needs attention when any agent is blocked, even mid-implementation', () => {
    const label = jobsSectionLabelFor(
      { implementation_launched_at: '2026-08-30T12:00:00Z' },
      [{ status: 'working' }, { status: 'blocked' }],
    )
    expect(label).toBe('Needs attention')
    expect(label).toBe(JOBS_SECTION_LABELS.NEEDS_ATTENTION)
  })

  it('returns Needs attention when any agent is silent', () => {
    const label = jobsSectionLabelFor(
      { implementation_launched_at: '2026-08-30T12:00:00Z' },
      [{ status: 'silent' }],
    )
    expect(label).toBe('Needs attention')
  })

  it('returns Needs attention when an agent has unread action-required posts', () => {
    const label = jobsSectionLabelFor(
      { implementation_launched_at: '2026-08-30T12:00:00Z' },
      [{ agent_display_name: 'orchestrator', status: 'working', action_required_unread: 1 }],
    )
    expect(label).toBe('Needs attention')
  })

  it('returns Needs decision when an agent awaits the user, ahead of blocked and unread', () => {
    const label = jobsSectionLabelFor(
      { implementation_launched_at: '2026-08-30T12:00:00Z' },
      [
        { agent_display_name: 'orchestrator', status: 'working', action_required_unread: 2 },
        { agent_display_name: 'implementer', status: 'blocked' },
        { agent_display_name: 'tester', status: 'awaiting_user' },
      ],
    )
    expect(label).toBe('Needs decision')
    expect(label).toBe(JOBS_SECTION_LABELS.NEEDS_DECISION)
  })

  it('no label in the set uses the retired wording', () => {
    for (const label of Object.values(JOBS_SECTION_LABELS)) {
      expect(label.toLowerCase()).not.toContain('needs input')
    }
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

  it('recognizes the orchestrator via agent_name even when agent_display_name differs', () => {
    const agents = [
      { agent_name: 'orchestrator', agent_display_name: 'Orchestrator (Phase 5)', status: 'closed' },
      { agent_display_name: 'implementer', status: 'complete' },
    ]
    expect(isReadyForReview({ status: 'active' }, agents)).toBe(true)
  })
})

describe('jobsSectionLabelFor on a finished project (TSK-9690)', () => {
  const done = [
    { agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'complete' },
    { agent_display_name: 'implementer', status: 'complete' },
  ]
  const launched = { staging_status: 'staging_complete', implementation_launched_at: '2026-09-26T13:00:00Z' }

  it('a completed project reads Complete, not Implementing', () => {
    expect(jobsSectionLabelFor({ ...launched, status: 'completed' }, done)).toBe('Complete')
  })

  it('a cancelled or terminated project reads Stopped', () => {
    expect(jobsSectionLabelFor({ ...launched, status: 'cancelled' }, done)).toBe('Stopped')
    expect(jobsSectionLabelFor({ ...launched, status: 'terminated' }, [])).toBe('Stopped')
  })

  it('an active project whose agents all finished still reads Review', () => {
    expect(jobsSectionLabelFor({ ...launched, status: 'active' }, done)).toBe('Review')
  })

  it('Complete is green like a complete agent; Stopped is quiet grey', () => {
    expect(jobsBoardLifecycleColor('Complete').toLowerCase()).toBe('#67bd6d')
    expect(jobsBoardLifecycleColor('Stopped').toLowerCase()).toBe('#999')
  })
})
