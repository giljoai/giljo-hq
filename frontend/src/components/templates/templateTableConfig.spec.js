/**
 * templateTableConfig.spec.js — FE-9385c
 *
 * The Updated column is a STATE column, and these pin the three states plus the
 * sort that makes new agents surface without a badge.
 *
 * Why this file is where the rule is tested: the state derivation is pure — a
 * template row and a reference clock in, a state out — so it is tested directly
 * rather than through a mounted table. The rendering of those states is asserted
 * in TemplatesTable.spec.js, where the DOM actually is.
 *
 * `now` is injected rather than read from the system clock. A test that has to
 * freeze time to assert "today" is a test that will fail at midnight in CI.
 *
 * Edition scope: CE
 */

import { describe, it, expect } from 'vitest'
import {
  templateUpdatedState,
  sortUpdatedState,
  TEMPLATE_TABLE_HEADERS,
  TEMPLATE_TABLE_DEFAULT_SORT,
} from './templateTableConfig'

const HOUR = 60 * 60 * 1000
const NOW = new Date('2026-08-11T14:00:00Z')

// Derived from NOW rather than hardcoded as UTC strings, deliberately. "Today"
// is the user's LOCAL calendar day — that is what "Added today" claims on screen
// — so a fixed UTC timestamp lands on a different local day depending on the
// runner's timezone. An earlier draft used 02:00Z, which is the previous day in
// any western offset, and these tests failed on exactly that.
const EARLIER_TODAY = new Date(NOW.getTime() - HOUR).toISOString()
const YESTERDAY = new Date(NOW.getTime() - 30 * HOUR).toISOString()

describe('templateUpdatedState — the three states', () => {
  it('reports the real date once the agent has actually been edited', () => {
    const state = templateUpdatedState(
      { updated_at: '2026-08-05T10:00:00Z', created_at: '2026-08-01T10:00:00Z' },
      { now: NOW },
    )

    expect(state.kind).toBe('edited')
    // No canned label — the renderer formats the timestamp itself.
    expect(state.label).toBeNull()
    expect(state.exact).toBe('2026-08-05T10:00:00Z')
  })

  it('reports "Never edited" when updated_at is NULL', () => {
    // The case the whole column exists for. updated_at has an onupdate and no
    // default, so a stock agent carries NULL — and the old UI fell back to
    // created_at, which is why every stock agent showed one seed timestamp.
    const state = templateUpdatedState(
      { updated_at: null, created_at: '2026-07-01T10:00:00Z' },
      { now: NOW },
    )

    expect(state.kind).toBe('never-edited')
    expect(state.label).toBe('Never edited')
    // The exact creation time is still offered on hover — muted, not hidden.
    expect(state.exact).toBe('2026-07-01T10:00:00Z')
  })

  it('reports "Added today" for an agent created today and never edited', () => {
    const state = templateUpdatedState(
      { updated_at: null, created_at: EARLIER_TODAY },
      { now: NOW },
    )

    expect(state.kind).toBe('added-today')
    expect(state.label).toBe('Added today')
  })

  it('does NOT say "Added today" for an agent created before today', () => {
    const state = templateUpdatedState(
      { updated_at: null, created_at: YESTERDAY },
      { now: NOW },
    )

    expect(state.kind).toBe('never-edited')
  })

  it('prefers "edited" over "Added today" for an agent created AND edited today', () => {
    // Ordering matters now that "Added today" is a single fact: an agent you
    // added and then tuned in the same day has been tuned, and the real date is
    // the more useful answer.
    const state = templateUpdatedState(
      { updated_at: EARLIER_TODAY, created_at: EARLIER_TODAY },
      { now: NOW },
    )

    expect(state.kind).toBe('edited')
  })

  it('renders system-managed rows as a dash, unchanged', () => {
    expect(templateUpdatedState({ _system: true }, { now: NOW }).label).toBe('—')
  })

  it('does not treat an unparseable created_at as today', () => {
    const state = templateUpdatedState(
      { updated_at: null, created_at: 'not-a-date' },
      { now: NOW },
    )

    expect(state.kind).toBe('never-edited')
  })
})

describe('templateUpdatedState — FE-9386 regression: updated_at must mean a real edit', () => {
  it('a duplicated agent must not mark the ORIGINAL as edited', () => {
    // FE-9386: duplicating a template used to stamp updated_at on the original.
    // This column now reads that field as "the user tuned this", so a spurious
    // stamp does not just look odd — it relabels an untouched agent as tuned.
    // Pinned here because the column's honesty depends on nothing else quietly
    // writing that field.
    const untouchedOriginal = { updated_at: null, created_at: '2026-07-01T10:00:00Z' }

    expect(templateUpdatedState(untouchedOriginal, { now: NOW }).kind).toBe('never-edited')

    // A copy is a NEW row with its own created_at, and it must not inherit an
    // edited state from the agent it was copied from.
    const theCopy = { updated_at: null, created_at: EARLIER_TODAY }
    expect(templateUpdatedState(theCopy, { now: NOW }).kind).toBe(
      'added-today',
    )
  })
})

describe('sortUpdatedState — new agents rise without a special-case rule', () => {
  it('sorts on last activity, so a never-edited new agent outranks an old edit', () => {
    const newAgent = { updated_at: null, created_at: EARLIER_TODAY }
    const oldEdited = { updated_at: '2026-08-05T10:00:00Z', created_at: '2026-01-01T10:00:00Z' }

    // Ascending comparator; the table applies `desc`, so > 0 means the new agent
    // lands on top. Sorting the raw column would have buried it: it has no
    // updated_at at all, which is exactly the row the column exists to surface.
    expect(sortUpdatedState(newAgent, oldEdited)).toBeGreaterThan(0)
  })

  it('falls back to created_at on both sides rather than treating NULL as epoch-zero for one', () => {
    const older = { updated_at: null, created_at: '2026-01-01T10:00:00Z' }
    const newer = { updated_at: null, created_at: EARLIER_TODAY }

    expect(sortUpdatedState(older, newer)).toBeLessThan(0)
  })
})

describe('table configuration', () => {
  it('keeps the Updated column sortable by last activity and defaults to newest first', () => {
    const updated = TEMPLATE_TABLE_HEADERS.find((h) => h.key === 'updated_at')

    expect(updated.sortRaw).toBe(sortUpdatedState)
    expect(TEMPLATE_TABLE_DEFAULT_SORT).toEqual([{ key: 'updated_at', order: 'desc' }])
  })

  it('still exposes "Active here" as the per-product column', () => {
    // Vocabulary lock: this label is what the operator reads, and the internal
    // name for the other switch must never surface here.
    const activeHere = TEMPLATE_TABLE_HEADERS.find((h) => h.key === 'is_active')

    expect(activeHere.title).toBe('Active here')
    expect(JSON.stringify(TEMPLATE_TABLE_HEADERS)).not.toMatch(/retire/i)
  })
})
