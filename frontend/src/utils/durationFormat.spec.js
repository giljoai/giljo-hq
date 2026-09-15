import { describe, it, expect } from 'vitest'
import {
  formatDurationSeconds,
  resolveAgentDurationSeconds,
  formatAgentDuration,
  formatTimeOfDay,
  elapsedSecondsSince,
} from './durationFormat'

describe('formatDurationSeconds', () => {
  it('renders "---" for null/undefined', () => {
    expect(formatDurationSeconds(null)).toBe('---')
    expect(formatDurationSeconds(undefined)).toBe('---')
  })

  it('renders seconds under a minute as "Ns"', () => {
    expect(formatDurationSeconds(42)).toBe('42s')
    expect(formatDurationSeconds(0)).toBe('0s')
  })

  it('renders under an hour as "Nm Ss"', () => {
    expect(formatDurationSeconds(207)).toBe('3m 27s')
  })

  it('renders an hour or more as "Nh Mm"', () => {
    expect(formatDurationSeconds(4320)).toBe('1h 12m')
  })

  it('floors negative/fractional input at 0', () => {
    expect(formatDurationSeconds(-5)).toBe('0s')
    expect(formatDurationSeconds(41.9)).toBe('41s')
  })
})

describe('resolveAgentDurationSeconds', () => {
  it('trusts backend duration_seconds for terminal statuses', () => {
    const now = Date.parse('2026-08-30T12:10:00Z')
    const agent = {
      status: 'complete',
      duration_seconds: 100,
      working_started_at: '2026-08-30T12:00:00Z',
    }
    expect(resolveAgentDurationSeconds(agent, now)).toBe(100)
  })

  it('trusts backend duration_seconds for closed status too', () => {
    const agent = { status: 'closed', duration_seconds: 4272 }
    expect(resolveAgentDurationSeconds(agent, Date.now())).toBe(4272)
  })

  it('ticks from working_started_at for a non-terminal agent', () => {
    const started = Date.parse('2026-08-30T12:00:00Z')
    const now = started + 41_000
    const agent = { status: 'working', working_started_at: '2026-08-30T12:00:00Z' }
    expect(resolveAgentDurationSeconds(agent, now)).toBe(41)
  })

  it('returns null when nothing usable is present', () => {
    expect(resolveAgentDurationSeconds({ status: 'staged' }, Date.now())).toBeNull()
  })
})

describe('formatAgentDuration', () => {
  it('combines resolve + format for a working agent', () => {
    const started = Date.parse('2026-08-30T12:00:00Z')
    const now = started + 4320_000
    const agent = { status: 'working', working_started_at: '2026-08-30T12:00:00Z' }
    expect(formatAgentDuration(agent, now)).toBe('1h 12m')
  })
})

describe('formatTimeOfDay', () => {
  it('returns "" for a missing/unparseable timestamp', () => {
    expect(formatTimeOfDay(null)).toBe('')
    expect(formatTimeOfDay(undefined)).toBe('')
    expect(formatTimeOfDay('not-a-date')).toBe('')
  })

  it('formats a valid ISO timestamp as a short local time', () => {
    expect(formatTimeOfDay('2026-08-30T22:14:00Z')).toMatch(/^\d{1,2}:\d{2}(\s?[AP]M)?$/)
  })
})

describe('elapsedSecondsSince', () => {
  it('returns null for a missing/unparseable timestamp', () => {
    expect(elapsedSecondsSince(null, Date.now())).toBeNull()
    expect(elapsedSecondsSince('nope', Date.now())).toBeNull()
  })

  it('computes elapsed seconds, floored at 0', () => {
    const anchor = Date.parse('2026-08-30T12:00:00Z')
    expect(elapsedSecondsSince('2026-08-30T12:00:00Z', anchor + 41_000)).toBe(41)
    expect(elapsedSecondsSince('2026-08-30T12:00:00Z', anchor - 5_000)).toBe(0)
  })
})
