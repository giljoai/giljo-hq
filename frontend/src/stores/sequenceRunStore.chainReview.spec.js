import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { computed } from 'vue'
import { useSequenceRunStore } from './sequenceRunStore'
import { resolveJobsNavPath } from '@/utils/jobsNavTarget'
import api from '@/services/api'

describe('sequenceRunStore — chain review (isReviewed / markReviewed)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('isReviewed returns false when the project has not been reviewed', () => {
    expect(store.isReviewed('run-1', 'p1')).toBe(false)
  })

  it('isReviewed returns false for null/empty inputs (defensive guard)', () => {
    expect(store.isReviewed(null, 'p1')).toBe(false)
    expect(store.isReviewed('run-1', null)).toBe(false)
    expect(store.isReviewed('', 'p1')).toBe(false)
  })

  it('markReviewed marks a project as reviewed', () => {
    store.markReviewed('run-1', 'p1')
    expect(store.isReviewed('run-1', 'p1')).toBe(true)
  })

  it('markReviewed is idempotent — calling twice does not throw or corrupt state', () => {
    store.markReviewed('run-1', 'p1')
    store.markReviewed('run-1', 'p1')
    expect(store.isReviewed('run-1', 'p1')).toBe(true)
  })

  it('markReviewed tracks pids per run independently (cross-run isolation)', () => {
    store.markReviewed('run-1', 'p1')
    store.markReviewed('run-2', 'p2')
    expect(store.isReviewed('run-1', 'p1')).toBe(true)
    expect(store.isReviewed('run-2', 'p2')).toBe(true)
    expect(store.isReviewed('run-1', 'p2')).toBe(false)
    expect(store.isReviewed('run-2', 'p1')).toBe(false)
  })

  it('a Vue computed that reads isReviewed re-evaluates after markReviewed (immutable Map trigger)', () => {
    const result = computed(() => store.isReviewed('run-1', 'p1'))
    expect(result.value).toBe(false)

    store.markReviewed('run-1', 'p1')

    expect(result.value).toBe(true)
  })

  it('$reset clears the reviewedProjects map', () => {
    store.markReviewed('run-1', 'p1')
    expect(store.isReviewed('run-1', 'p1')).toBe(true)

    store.$reset()

    expect(store.isReviewed('run-1', 'p1')).toBe(false)
  })
})


describe('sequenceRunStore — reviewPendingRun getter', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('returns the run when finished (not in activeRuns) but has unreviewed completed members (RED→GREEN)', () => {
    store._testSetActiveRun({
      id: 'run-1',
      resolved_order: ['p1', 'p2'],
      project_statuses: { p1: 'completed', p2: 'completed' },
    })
    expect(store.activeRuns).toHaveLength(0)
    expect(store.reviewPendingRun).not.toBeNull()
    expect(store.reviewPendingRun.id).toBe('run-1')
  })

  it('returns null after all completed members are reviewed — release-on-all-reviewed, no bounce', () => {
    store._testSetActiveRun({
      id: 'run-1',
      resolved_order: ['p1', 'p2'],
      project_statuses: { p1: 'completed', p2: 'completed' },
    })
    expect(store.reviewPendingRun).not.toBeNull()

    store.markReviewed('run-1', 'p1')
    store.markReviewed('run-1', 'p2')

    expect(store.reviewPendingRun).toBeNull()
  })

  it('board integration — a finished+unreviewed run is still the run the board reads, then releases', () => {
    store._testSetActiveRun({
      id: 'run-1',
      resolved_order: ['p1', 'p2'],
      project_statuses: { p1: 'completed', p2: 'completed' },
    })

    expect(store.activeRuns[0] ?? store.reviewPendingRun ?? null).toMatchObject({ id: 'run-1' })
    expect(resolveJobsNavPath()).toBe('/jobs-overview')

    store.markReviewed('run-1', 'p1')
    store.markReviewed('run-1', 'p2')
    expect(store.activeRuns[0] ?? store.reviewPendingRun ?? null).toBeNull()
  })

  it('ordering: in-flight run in activeRuns[0] takes precedence; reviewPendingRun is not consulted (?? short-circuits)', () => {
    store._testSeedRuns([
      {
        id: 'run-active',
        resolved_order: ['pX'],
        project_ids: ['pX'],
        project_statuses: { pX: 'running' },
        status: 'running',
      },
    ])
    store._testSetActiveRun({
      id: 'run-finished',
      resolved_order: ['p1', 'p2'],
      project_statuses: { p1: 'completed', p2: 'completed' },
    })

    expect(store.activeRuns[0]).toBeDefined()
    expect(store.activeRuns[0].id).toBe('run-active')

    expect(store.activeRuns[0] ?? store.reviewPendingRun ?? null).toMatchObject({
      id: 'run-active',
    })
  })

  it('returns null when activeRun is null (no solo or chain run open)', () => {
    expect(store.reviewPendingRun).toBeNull()
  })
})


describe('sequenceRunStore — FE-9104 cold-refresh review reachability', () => {
  let store

  const termRun = (extra = {}) => ({
    id: 'run-term',
    resolved_order: ['p1', 'p2'],
    project_ids: ['p1', 'p2'],
    project_statuses: { p1: 'completed', p2: 'completed' },
    status: 'completed',
    ...extra,
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('cold refresh: terminal run in reviewPendingById (activeRun null) → reviewPendingRun resolves + nav → ?run (RED→GREEN)', () => {
    store._testSeedReviewPending([termRun()])
    expect(store.activeRun).toBeNull()
    expect(store.activeRuns).toHaveLength(0)
    expect(store.reviewPendingRun).not.toBeNull()
    expect(store.reviewPendingRun.id).toBe('run-term')

    expect(store.activeRuns[0] ?? store.reviewPendingRun ?? null).toMatchObject({
      id: 'run-term',
    })
  })

  it('release: after every completed member reviewed → reviewPendingRun releases (no bounce)', () => {
    store._testSeedReviewPending([termRun()])
    expect(store.reviewPendingRun).not.toBeNull()

    store.markReviewed('run-term', 'p1')
    store.markReviewed('run-term', 'p2')

    expect(store.reviewPendingRun).toBeNull()
    expect(store.activeRuns[0] ?? store.reviewPendingRun ?? null).toBeNull()
  })

  it('hydrate splits runs: active → runsById (locks checkbox), terminal review-pending → reviewPendingById (does NOT re-lock)', async () => {
    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [
        {
          id: 'run-active',
          resolved_order: ['pA'],
          project_ids: ['pA'],
          project_statuses: { pA: 'running' },
          status: 'running',
        },
        termRun(),
      ],
    })
    await store.hydrate()

    expect(store.activeRuns.map((r) => r.id)).toEqual(['run-active'])
    expect(store.isProjectInActiveChain('pA')).toBe(true)
    expect(store.isProjectInActiveChain('p1')).toBe(false)
    expect(store.reviewPendingById.has('run-term')).toBe(true)
    expect(store.reviewPendingRun.id).toBe('run-term')
    expect(api.sequenceRuns.list).toHaveBeenCalledWith({
      status: 'pending,running,stalled',
      include_review_pending: true,
    })
  })

  it('solo deletion test: empty hydrate → no run to review, and the Jobs landing is still the board', async () => {
    api.sequenceRuns.list.mockResolvedValueOnce({ data: [] })
    await store.hydrate()

    expect(store.reviewPendingRun).toBeNull()
    expect(store.activeRuns).toHaveLength(0)
    expect(resolveJobsNavPath()).toBe('/jobs-overview')
  })

  it('$reset clears reviewPendingById', () => {
    store._testSeedReviewPending([termRun()])
    expect(store.reviewPendingRun).not.toBeNull()

    store.$reset()

    expect(store.reviewPendingRun).toBeNull()
    expect(store.reviewPendingById.size).toBe(0)
  })
})
