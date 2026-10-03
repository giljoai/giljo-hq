import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSequenceRunStore } from './sequenceRunStore'
import api from '@/services/api'

function run(id, projectIds, status = 'pending', extra = {}) {
  return {
    id,
    project_ids: projectIds,
    resolved_order: projectIds,
    current_index: 0,
    status,
    execution_mode: 'subagent',
    project_statuses: projectIds.reduce((acc, p) => ({ ...acc, [p]: 'pending' }), {}),
    locked: false,
    ...extra,
  }
}

describe('sequenceRunStore FE-9632 — isRunning', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('is false for a pending run whose head has not started (the pre-run screen)', () => {
    store._testSeedRuns([run('r1', ['pA', 'pB'], 'pending')])
    expect(store.isRunning('r1')).toBe(false)
  })

  it('stays false for a STAGED (locked) pending run — locked is the staged tier, not a status', () => {
    store._testSeedRuns([run('r1', ['pA', 'pB'], 'pending', { locked: true })])
    expect(store.isRunning('r1')).toBe(false)
  })

  it('is true when the run status is running', () => {
    store._testSeedRuns([run('r1', ['pA', 'pB'], 'running')])
    expect(store.isRunning('r1')).toBe(true)
  })

  it('is true when the run status is stalled', () => {
    store._testSeedRuns([run('r1', ['pA', 'pB'], 'stalled')])
    expect(store.isRunning('r1')).toBe(true)
  })

  it('is true when the HEAD member has started even if the run status lags (stale FE state)', () => {
    store._testSeedRuns([
      run('r1', ['pA', 'pB'], 'pending', { project_statuses: { pA: 'implementing', pB: 'pending' } }),
    ])
    expect(store.isRunning('r1')).toBe(true)
  })

  it('treats a head status of planning as started (FE-9493 first-signal value)', () => {
    store._testSeedRuns([
      run('r1', ['pA', 'pB'], 'pending', { project_statuses: { pA: 'planning', pB: 'pending' } }),
    ])
    expect(store.isRunning('r1')).toBe(true)
  })

  it("does not treat a head status of 'staged' as started", () => {
    store._testSeedRuns([
      run('r1', ['pA', 'pB'], 'pending', { project_statuses: { pA: 'staged', pB: 'pending' } }),
    ])
    expect(store.isRunning('r1')).toBe(false)
  })

  it('reads the head from resolved_order, not project_ids order', () => {
    store._testSeedRuns([
      run('r1', ['pA', 'pB'], 'pending', {
        resolved_order: ['pB', 'pA'],
        project_statuses: { pA: 'implementing', pB: 'pending' },
      }),
    ])
    expect(store.isRunning('r1')).toBe(false)
  })

  it('is false for an unknown run id rather than throwing', () => {
    expect(store.isRunning('nope')).toBe(false)
  })

  it('is false once the run has finished (a cancelled run is not running)', () => {
    store._testSeedRuns([run('r1', ['pA'], 'cancelled', { project_statuses: { pA: 'terminated' } })])
    expect(store.isRunning('r1')).toBe(false)
  })
})

describe('sequenceRunStore FE-9632 — stopChain', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
    vi.restoreAllMocks()
  })

  it('POSTs the phase-2 stop route for the run', async () => {
    const stop = vi.spyOn(api.sequenceRuns, 'stop').mockResolvedValue({ data: run('r1', ['pA'], 'cancelled') })

    await store.stopChain('r1')

    expect(stop).toHaveBeenCalledWith('r1')
  })

  it('re-hydrates afterwards so the stopped run leaves the active set', async () => {
    vi.spyOn(api.sequenceRuns, 'stop').mockResolvedValue({ data: run('r1', ['pA'], 'cancelled') })
    const list = vi.spyOn(api.sequenceRuns, 'list').mockResolvedValue({ data: [] })

    await store.stopChain('r1')

    expect(list).toHaveBeenCalled()
  })

  it('returns the stopped run so the caller can confirm the terminal status', async () => {
    vi.spyOn(api.sequenceRuns, 'stop').mockResolvedValue({ data: run('r1', ['pA'], 'cancelled') })

    const stopped = await store.stopChain('r1')

    expect(stopped.status).toBe('cancelled')
  })

  it('propagates a failure instead of reporting a stop that did not happen', async () => {
    vi.spyOn(api.sequenceRuns, 'stop').mockRejectedValue(new Error('boom'))
    const list = vi.spyOn(api.sequenceRuns, 'list').mockResolvedValue({ data: [] })

    await expect(store.stopChain('r1')).rejects.toThrow('boom')
    expect(list).not.toHaveBeenCalled()
  })
})
