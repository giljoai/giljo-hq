/**
 * jobsBoardCardStats.spec.js — FE-9548
 *
 * Pure unit tests for the Jobs board card's aggregate stat strip + meta
 * line arithmetic. Fixture numbers mirror the v4 mock's own BE-6174 example
 * card (steps 7/12, agents 3, waiting 1, duration 41m) so a regression here
 * would also fail the visual comparison against the mock.
 *
 * Edition scope: Both.
 */
import { describe, it, expect } from 'vitest'
import { aggregateSteps, aggregateWaiting, projectDurationSeconds, jobsBoardMetaLine } from './jobsBoardCardStats'
import { JOBS_SECTION_LABELS } from './jobsSectionLabel'

const mockCardAgents = [
  { steps: { completed: 3, total: 4 }, messages_waiting_count: 1 },
  { steps: { completed: 2, total: 6 }, messages_waiting_count: 0 },
  { steps: { completed: 2, total: 2 }, messages_waiting_count: 0 },
]

describe('aggregateSteps', () => {
  it('sums completed/total across all agents (mock BE-6174: 7/12)', () => {
    expect(aggregateSteps(mockCardAgents)).toEqual({ completed: 7, total: 12, hasSteps: true })
  })

  it('reports hasSteps=false and zeros when no agent carries a numeric steps summary', () => {
    expect(aggregateSteps([{ status: 'staged' }])).toEqual({ completed: 0, total: 0, hasSteps: false })
  })

  it('defaults to an empty agent list without throwing', () => {
    expect(aggregateSteps()).toEqual({ completed: 0, total: 0, hasSteps: false })
  })
})

describe('aggregateWaiting', () => {
  it('sums messages_waiting_count across all agents (mock BE-6174: 1)', () => {
    expect(aggregateWaiting(mockCardAgents)).toBe(1)
  })

  it('treats a missing count as zero', () => {
    expect(aggregateWaiting([{}, { messages_waiting_count: 2 }])).toBe(2)
  })
})

describe('projectDurationSeconds', () => {
  it('returns null before implementation has launched (Staged)', () => {
    expect(projectDurationSeconds({ implementation_launched_at: null }, Date.now())).toBeNull()
  })

  it('ticks from implementation_launched_at while in flight', () => {
    const launched = Date.parse('2026-08-30T22:14:00Z')
    const now = launched + 41 * 60_000
    expect(projectDurationSeconds({ implementation_launched_at: '2026-08-30T22:14:00Z' }, now)).toBe(41 * 60)
  })

  it('freezes at completed_at once the project is done (Review)', () => {
    const launched = '2026-08-30T22:29:00Z'
    const completed = '2026-08-30T23:41:00Z' // 1h12m later
    const farFuture = Date.parse(completed) + 999_000
    expect(
      projectDurationSeconds({ implementation_launched_at: launched, completed_at: completed }, farFuture),
    ).toBe(72 * 60)
  })
})

describe('jobsBoardMetaLine', () => {
  it('Staged: "staged HH:MM · awaiting your go"', () => {
    const line = jobsBoardMetaLine(
      { created_at: '2026-08-30T23:20:00Z' },
      JOBS_SECTION_LABELS.STAGED,
      Date.now(),
    )
    expect(line).toContain('awaiting your go')
    expect(line.startsWith('staged ')).toBe(true)
  })

  it('Implementing: "launched HH:MM · Nm elapsed" (mock BE-6174: 41m)', () => {
    const launched = Date.parse('2026-08-30T22:14:00Z')
    const now = launched + 41 * 60_000
    const line = jobsBoardMetaLine(
      { implementation_launched_at: '2026-08-30T22:14:00Z' },
      JOBS_SECTION_LABELS.IMPLEMENTING,
      now,
    )
    expect(line).toContain('41m')
    expect(line).toContain('elapsed')
    expect(line.startsWith('launched ')).toBe(true)
  })

  it('Review: "completed HH:MM · Nh Mm total" (mock BE-6177: 1h 12m)', () => {
    const line = jobsBoardMetaLine(
      { implementation_launched_at: '2026-08-30T22:29:00Z', completed_at: '2026-08-30T23:41:00Z' },
      JOBS_SECTION_LABELS.REVIEW,
      Date.now(),
    )
    expect(line).toContain('1h 12m')
    expect(line).toContain('total')
    expect(line.startsWith('completed ')).toBe(true)
  })

  // FE-9551 REGRESSION: Activated/Planning are new pre-launch states with no
  // implementation_launched_at -- without an explicit branch they fell into
  // the default "launched/elapsed" text, which rendered the nonsensical
  // "--- elapsed" (formatDurationSeconds(null) === '---') for a project that
  // has never launched.
  it('Planning: does not fall into the launched/elapsed default', () => {
    const line = jobsBoardMetaLine({}, JOBS_SECTION_LABELS.PLANNING, Date.now())
    expect(line).not.toContain('---')
    expect(line).not.toContain('elapsed')
    expect(line.toLowerCase()).toContain('staging')
  })

  it('Activated: does not fall into the launched/elapsed default', () => {
    const line = jobsBoardMetaLine({ created_at: '2026-08-31T10:00:00Z' }, JOBS_SECTION_LABELS.ACTIVATED, Date.now())
    expect(line).not.toContain('---')
    expect(line).not.toContain('elapsed')
    expect(line.toLowerCase()).toContain('staged')
  })
})
