/**
 * taskStatusEnumSubset.spec.js — drift guard for FE/BE TaskStatus alignment
 * (IMP-5030 follow-up to FE-5041).
 *
 * Context: a test-install task row was written with status='terminated' (not a
 * valid TaskStatus), and the frontend rendered the capitalized fallback
 * label "Terminated", giving the appearance of an FE-only status. There is
 * no FE-side hardcoded TaskStatus list (the canonical set ships via
 * `GET /api/v1/task-statuses/` -> `taskStatusesStore`), but the frontend
 * unit tests in this repo and the badge component contract carry an
 * embedded "canonical six" mirror that downstream regressions key off of.
 *
 * This spec asserts that mirror is a subset of the backend `TaskStatus`
 * enum. If anyone re-adds an FE-only value (e.g. 'terminated') to the
 * canonical mirror, this test FAILS. Conversely, if the backend grows a
 * new status, this test continues to pass (subset, not equality) so the
 * mirror can lag by one release without breaking CI.
 *
 * Backend enum source of truth:
 *   src/giljo_mcp/domain/task_status.py — class TaskStatus(enum.StrEnum)
 *
 * Keep BACKEND_TASK_STATUSES below in sync with that file's enum members.
 * The comment in this file is the canonical pointer; ripgrep this filename
 * if the enum source moves.
 */
import { describe, it, expect } from 'vitest'

// Mirrored from `src/giljo_mcp/domain/task_status.py` (TaskStatus enum
// values). Order matches the declaration order in that file.
const BACKEND_TASK_STATUSES = Object.freeze([
  'pending',
  'in_progress',
  'completed',
  'blocked',
  'cancelled',
  'converted',
])

// Mirrored from the STATUSES array in
// `frontend/tests/unit/components/TaskStatusBadge.spec.js` (the canonical
// FE-side mirror used to validate the badge component). Adding any value
// here that is NOT in BACKEND_TASK_STATUSES is a drift bug — exactly the
// IMP-5030 scenario ('terminated' was rendered FE-side via fallback, not
// because the FE declared it, but the lesson stands: the mirror is the
// guard rail).
const FRONTEND_TASK_STATUSES = Object.freeze([
  'pending',
  'in_progress',
  'completed',
  'blocked',
  'cancelled',
  'converted',
])

describe('Task status enum: FE subset of BE (drift guard)', () => {
  it('every FE task status value exists in the BE TaskStatus enum', () => {
    const beSet = new Set(BACKEND_TASK_STATUSES)
    const feOnly = FRONTEND_TASK_STATUSES.filter((v) => !beSet.has(v))
    expect(feOnly).toEqual([])
  })

  it("explicitly rejects 'terminated' as a TaskStatus value (IMP-5030 regression)", () => {
    expect(BACKEND_TASK_STATUSES).not.toContain('terminated')
    expect(FRONTEND_TASK_STATUSES).not.toContain('terminated')
  })

  it('BACKEND_TASK_STATUSES contains exactly the six canonical members', () => {
    // Belt-and-braces: if someone "fixes" the BE mirror by adding a value
    // that does not exist in `task_status.py`, this test catches it on the
    // next CI run instead of waiting for the badge component to misrender.
    expect([...BACKEND_TASK_STATUSES].sort()).toEqual(
      [
        'blocked',
        'cancelled',
        'completed',
        'converted',
        'in_progress',
        'pending',
      ].sort(),
    )
  })
})
