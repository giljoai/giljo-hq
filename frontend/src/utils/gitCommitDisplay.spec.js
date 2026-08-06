import { describe, it, expect } from 'vitest'
import { commitTitle, shortSha } from './gitCommitDisplay'

// BE-9256 layer 4 — UI floor for legacy titleless git_commits rows.
//
// Stored 360/closeout rows already contain git_commits entries with an EMPTY
// message (legacy bare-SHA normalization, pre-validator). The backend now
// rejects NEW titleless commits, but old rows stay as-is (tolerance per the
// data-facing-convention DoD). Every render surface must show a floor: the
// short SHA, never a blank string or a bare "-".

describe('shortSha', () => {
  it('truncates a full SHA to the first 8 characters', () => {
    expect(shortSha('569905bd0abcdef1234567890')).toBe('569905bd')
  })

  it('returns empty string for a missing/falsy sha', () => {
    expect(shortSha(undefined)).toBe('')
    expect(shortSha(null)).toBe('')
    expect(shortSha('')).toBe('')
  })

  it('returns a non-string sha as empty string rather than throwing', () => {
    expect(shortSha(12345)).toBe('')
  })
})

describe('commitTitle', () => {
  it('renders the message when present (titled row, unchanged)', () => {
    expect(commitTitle({ sha: '569905bd0abc', message: 'BE-9256: fail-closed validator' })).toBe(
      'BE-9256: fail-closed validator'
    )
  })

  it('falls back to the short SHA when message is an empty string (legacy row)', () => {
    expect(commitTitle({ sha: '569905bd0abcdef', message: '' })).toBe('569905bd')
  })

  it('falls back to the short SHA when message is missing entirely (legacy row)', () => {
    expect(commitTitle({ sha: '569905bd0abcdef' })).toBe('569905bd')
  })

  it('falls back to the short SHA when message is whitespace-only', () => {
    expect(commitTitle({ sha: '569905bd0abcdef', message: '   ' })).toBe('569905bd')
  })

  it('never renders a bare "-" for a row that has a sha', () => {
    const title = commitTitle({ sha: '569905bd0abcdef', message: '' })
    expect(title).not.toBe('-')
    expect(title).not.toBe('')
  })

  it('keeps today\'s placeholder behavior (empty string) when sha is ALSO missing', () => {
    expect(commitTitle({ message: '' })).toBe('')
    expect(commitTitle({})).toBe('')
  })

  it('does not throw on null/undefined commit', () => {
    expect(commitTitle(null)).toBe('')
    expect(commitTitle(undefined)).toBe('')
  })
})
