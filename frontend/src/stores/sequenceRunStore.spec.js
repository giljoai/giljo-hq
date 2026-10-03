import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSequenceRunStore } from './sequenceRunStore'
import api from '@/services/api'

function run(id, projectIds, status = 'running', extra = {}) {
  return {
    id,
    project_ids: projectIds,
    resolved_order: projectIds,
    current_index: 0,
    status,
    execution_mode: 'multi_terminal',
    project_statuses: projectIds.reduce((acc, p) => ({ ...acc, [p]: 'pending' }), {}),
    ...extra,
  }
}

describe('sequenceRunStore (FE-6165f)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  describe('hydrate', () => {
    it('populates runsById from a BARE ARRAY (BE-6165e list shape)', async () => {
      api.sequenceRuns.list.mockResolvedValueOnce({ data: [run('r1', ['pA', 'pB']), run('r2', ['pC'])] })
      await store.hydrate()
      expect(store.activeRuns).toHaveLength(2)
      expect(store.runsById.get('r1').project_ids).toEqual(['pA', 'pB'])
      expect(api.sequenceRuns.list).toHaveBeenCalledWith({
        status: 'pending,running,stalled',
        include_review_pending: true,
      })
    })

    it('rebuilds (drops a run no longer in the active list)', async () => {
      api.sequenceRuns.list.mockResolvedValueOnce({ data: [run('r1', ['pA']), run('r2', ['pB'])] })
      await store.hydrate()
      expect(store.activeRuns).toHaveLength(2)
      api.sequenceRuns.list.mockResolvedValueOnce({ data: [run('r1', ['pA'])] })
      await store.hydrate()
      expect(store.activeRuns).toHaveLength(1)
      expect(store.isProjectInActiveChain('pB')).toBe(false)
    })

    it('sets error and leaves state empty on failure', async () => {
      api.sequenceRuns.list.mockRejectedValueOnce(new Error('boom'))
      await store.hydrate()
      expect(store.error).toBeTruthy()
      expect(store.activeRuns).toHaveLength(0)
    })
  })

  describe('membership getters', () => {
    beforeEach(() => {
      store._testSeedRuns([run('r1', ['pA', 'pB']), run('r2', ['pC'])])
    })

    it('isProjectInActiveChain is true for members, false otherwise', () => {
      expect(store.isProjectInActiveChain('pA')).toBe(true)
      expect(store.isProjectInActiveChain('pC')).toBe(true)
      expect(store.isProjectInActiveChain('pX')).toBe(false)
      expect(store.isProjectInActiveChain('')).toBe(false)
    })

    it('runForProject returns the containing run', () => {
      expect(store.runForProject('pB').id).toBe('r1')
      expect(store.runForProject('pC').id).toBe('r2')
      expect(store.runForProject('pX')).toBeNull()
    })

    it('projectChainStatus returns the per-project status', () => {
      expect(store.projectChainStatus('pA')).toBe('pending')
      expect(store.projectChainStatus('pX')).toBeNull()
    })

    it('activeChainProjectIds is the union of all members', () => {
      expect(store.activeChainProjectIds.sort()).toEqual(['pA', 'pB', 'pC'])
    })
  })

  describe('patchRun', () => {
    it('PATCHes and refreshes the election entry', async () => {
      store._testSeedRuns([run('r1', ['pA'], 'running')])
      api.sequenceRuns.update.mockResolvedValueOnce({ data: run('r1', ['pA'], 'running', { execution_mode: 'subagent' }) })
      const updated = await store.patchRun('r1', { execution_mode: 'subagent' })
      expect(api.sequenceRuns.update).toHaveBeenCalledWith('r1', { execution_mode: 'subagent' })
      expect(updated.execution_mode).toBe('subagent')
      expect(store.runsById.get('r1').execution_mode).toBe('subagent')
    })

    it('drops the run from the election set when PATCHed to a terminal status', async () => {
      store._testSeedRuns([run('r1', ['pA'], 'running')])
      api.sequenceRuns.update.mockResolvedValueOnce({ data: run('r1', ['pA'], 'cancelled') })
      await store.patchRun('r1', { status: 'cancelled' })
      expect(store.isProjectInActiveChain('pA')).toBe(false)
    })
  })

  describe('handleSequenceUpdated (WS re-fetch)', () => {
    it('re-hydrates the active set from the {run_id}-only payload', async () => {
      store._testSeedRuns([run('r1', ['pA']), run('r2', ['pB'])])
      api.sequenceRuns.list.mockResolvedValueOnce({ data: [run('r1', ['pA'])] })
      await store.handleSequenceUpdated({ run_id: 'r2' })
      expect(api.sequenceRuns.list).toHaveBeenCalled()
      expect(store.isProjectInActiveChain('pB')).toBe(false)
    })
  })

  it('$reset clears all state', () => {
    store._testSeedRuns([run('r1', ['pA'])])
    store.$reset()
    expect(store.activeRuns).toHaveLength(0)
  })
})

describe('normalizeRun — chain_mission preserved (FE-6199 B1)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('preserves chain_mission string', () => {
    store._testSeedRuns([{
      id: 'r1',
      project_ids: ['pA'],
      resolved_order: ['pA'],
      current_index: 0,
      status: 'pending',
      execution_mode: null,
      project_statuses: {},
      chain_mission: 'Build the whole feature end-to-end',
    }])
    expect(store.runsById.get('r1').chain_mission).toBe('Build the whole feature end-to-end')
  })

  it('defaults chain_mission to null when absent', () => {
    store._testSeedRuns([{
      id: 'r2',
      project_ids: ['pB'],
      resolved_order: ['pB'],
      current_index: 0,
      status: 'pending',
      execution_mode: null,
      project_statuses: {},
    }])
    expect(store.runsById.get('r2').chain_mission).toBeNull()
  })
})

describe('handleSequenceUpdated — chain eject guard (UI-2)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('does NOT eject when a member closes but the run stays active (still in hydrate list)', async () => {
    store._testSeedRuns([run('r1', ['p1', 'p2'], 'running')])

    api.sequenceRuns.list.mockResolvedValueOnce({ data: [run('r1', ['p1', 'p2'], 'running', {
      project_statuses: { p1: 'completed', p2: 'implementing' },
    })] })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.isProjectInActiveChain('p1')).toBe(true)
    expect(store.isProjectInActiveChain('p2')).toBe(true)
    expect(store.runsById.get('r1')?.project_statuses?.p1).toBe('completed')
    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
  })
})

describe('handleSequenceUpdated — chain staging live-fill (FE-6199)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('updates chain_mission when conductor writes chain mission (still-active run)', async () => {
    const initial = run('r1', ['p1', 'p2'], 'pending', { chain_mission: null, locked: true })
    store._testSeedRuns([initial])

    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', {
        chain_mission: 'Build A then wire B',
        locked: true,
      })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.runsById.get('r1')?.chain_mission).toBe('Build A then wire B')
    expect(store.isProjectInActiveChain('p1')).toBe(true)
    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
  })

  it('updates locked to true when Stage Chain is pressed (still-active run)', async () => {
    const initial = run('r1', ['p1', 'p2'], 'pending', { locked: false, chain_mission: null })
    store._testSeedRuns([initial])

    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: null })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.runsById.get('r1')?.locked).toBe(true)
  })

  it('arms chainImplementReady-relevant fields in one sequence:updated round-trip', async () => {
    const initial = run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: null })
    store._testSeedRuns([initial])

    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: 'Full delivery plan' })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.runsById.get('r1')?.locked).toBe(true)
    expect(store.runsById.get('r1')?.chain_mission).toBe('Full delivery plan')
    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
  })
})



describe('sequenceRunStore.isProjectStartable (FE-9629)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  function chain(extra = {}) {
    return run('r1', ['p1', 'p2', 'p3'], 'running', extra)
  }

  it('is true for the member at the current index', () => {
    store._testSeedRuns([chain({ current_index: 0 })])
    expect(store.isProjectStartable('p1')).toBe(true)
  })

  it('is false for a member past the index whose predecessor has not completed', () => {
    store._testSeedRuns([chain({ current_index: 0, project_statuses: { p1: 'planning', p2: 'pending', p3: 'pending' } })])
    expect(store.isProjectStartable('p2')).toBe(false)
    expect(store.isProjectStartable('p3')).toBe(false)
  })

  it('arms the next member the moment its predecessor completes', () => {
    store._testSeedRuns([chain({ current_index: 0, project_statuses: { p1: 'completed', p2: 'pending', p3: 'pending' } })])
    expect(store.isProjectStartable('p2')).toBe(true)
    expect(store.isProjectStartable('p3')).toBe(false)
  })

  it('stays true for a member the index has already passed (never rewinds the affordance)', () => {
    store._testSeedRuns([chain({ current_index: 2 })])
    expect(store.isProjectStartable('p1')).toBe(true)
    expect(store.isProjectStartable('p2')).toBe(true)
  })

  it('is false once the member itself has finished', () => {
    store._testSeedRuns([chain({ current_index: 1, project_statuses: { p1: 'completed', p2: 'pending', p3: 'pending' } })])
    expect(store.isProjectStartable('p1')).toBe(false)
  })

  it('is false for a project that is in no active chain (the solo path)', () => {
    store._testSeedRuns([chain()])
    expect(store.isProjectStartable('solo-pid')).toBe(false)
    expect(store.isProjectStartable('')).toBe(false)
    expect(store.isProjectStartable(null)).toBe(false)
  })
})
