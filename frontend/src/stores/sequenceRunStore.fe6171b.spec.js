import { describe, it, expect, beforeEach } from 'vitest'
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
    execution_mode: 'multi_terminal',
    project_statuses: projectIds.reduce((acc, p) => ({ ...acc, [p]: 'pending' }), {}),
    locked: false,
    ...extra,
  }
}

describe('sequenceRunStore FE-6171b — locked flag', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })


  it('normalises locked=true from raw run', () => {
    store._testSeedRuns([run('r1', ['pA'], 'pending', { locked: true })])
    expect(store.runsById.get('r1').locked).toBe(true)
  })

  it('normalises locked=false from raw run', () => {
    store._testSeedRuns([run('r1', ['pA'], 'pending', { locked: false })])
    expect(store.runsById.get('r1').locked).toBe(false)
  })

  it('defaults locked to false when absent from raw run (pre-migration rows)', () => {
    const rawWithoutLocked = { id: 'r2', project_ids: ['pB'], resolved_order: ['pB'],
      current_index: 0, status: 'pending', execution_mode: 'multi_terminal',
      project_statuses: { pB: 'pending' } }
    store._testSeedRuns([rawWithoutLocked])
    expect(store.runsById.get('r2').locked).toBe(false)
  })


  it('isProjectRunLocked returns true when run.locked=true', () => {
    store._testSeedRuns([run('r1', ['pA', 'pB'], 'pending', { locked: true })])
    expect(store.isProjectRunLocked('pA')).toBe(true)
    expect(store.isProjectRunLocked('pB')).toBe(true)
  })

  it('isProjectRunLocked returns false when run.locked=false (Editing tier)', () => {
    store._testSeedRuns([run('r1', ['pA'], 'pending', { locked: false })])
    expect(store.isProjectRunLocked('pA')).toBe(false)
  })

  it('isProjectRunLocked returns false when project not in any chain', () => {
    store._testSeedRuns([run('r1', ['pA'], 'pending', { locked: true })])
    expect(store.isProjectRunLocked('pX')).toBe(false)
    expect(store.isProjectRunLocked('')).toBe(false)
  })

  it('isProjectRunLocked is reactive: reflects store update after lockRun', async () => {
    store._testSeedRuns([run('r1', ['pA'], 'pending', { locked: false })])
    api.sequenceRuns.update.mockResolvedValueOnce({ data: run('r1', ['pA'], 'pending', { locked: true }) })
    await store.lockRun('r1')
    expect(store.isProjectRunLocked('pA')).toBe(true)
  })


  it('lockRun PATCHes locked=true and updates the store', async () => {
    store._testSeedRuns([run('r1', ['pA'], 'pending', { locked: false })])
    api.sequenceRuns.update.mockResolvedValueOnce({ data: run('r1', ['pA'], 'pending', { locked: true }) })

    const updated = await store.lockRun('r1')

    expect(api.sequenceRuns.update).toHaveBeenCalledWith('r1', { locked: true })
    expect(updated.locked).toBe(true)
    expect(store.runsById.get('r1').locked).toBe(true)
  })


  it('unlockRun PATCHes locked=false and updates the store', async () => {
    store._testSeedRuns([run('r1', ['pA'], 'pending', { locked: true })])
    api.sequenceRuns.update.mockResolvedValueOnce({ data: run('r1', ['pA'], 'pending', { locked: false }) })

    const updated = await store.unlockRun('r1')

    expect(api.sequenceRuns.update).toHaveBeenCalledWith('r1', { locked: false })
    expect(updated.locked).toBe(false)
    expect(store.runsById.get('r1').locked).toBe(false)
  })

  it('unlockRun does NOT dissolve the run (chain stays intact)', async () => {
    store._testSeedRuns([run('r1', ['pA', 'pB'], 'pending', { locked: true })])
    api.sequenceRuns.update.mockResolvedValueOnce({
      data: run('r1', ['pA', 'pB'], 'pending', { locked: false }),
    })

    await store.unlockRun('r1')

    expect(store.isProjectInActiveChain('pA')).toBe(true)
    expect(store.isProjectInActiveChain('pB')).toBe(true)
    expect(store.runsById.has('r1')).toBe(true)
  })
})
