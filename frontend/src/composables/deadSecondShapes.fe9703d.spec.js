import { describe, it, expect } from 'vitest'
import { extractJobsFromResponse } from './useAgentJobs'

describe('extractJobsFromResponse', () => {
  it('reads the { jobs } envelope the endpoint sends', () => {
    expect(extractJobsFromResponse({ jobs: [{ job_id: 'j1' }], total: 1, limit: 50, offset: 0 })).toEqual([
      { job_id: 'j1' },
    ])
  })

  it('raises on any other shape instead of answering "no agents"', () => {
    expect(() => extractJobsFromResponse({ rows: [] })).toThrow()
    expect(() => extractJobsFromResponse([])).toThrow()
    expect(() => extractJobsFromResponse(undefined)).toThrow()
  })
})
