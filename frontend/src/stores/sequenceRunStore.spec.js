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

    it('tolerates a wrapped {sequence_runs:[]} payload as a fallback', async () => {
      api.sequenceRuns.list.mockResolvedValueOnce({ data: { sequence_runs: [run('r9', ['pZ'])] } })
      await store.hydrate()
      expect(store.activeRuns).toHaveLength(1)
      expect(store.isProjectInActiveChain('pZ')).toBe(true)
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

  describe('setActiveRun / fetchRun', () => {
    it('setActiveRun stores the cockpit run and adds active runs to the election set', () => {
      store.setActiveRun(run('r5', ['pQ'], 'pending'))
      expect(store.activeRun.id).toBe('r5')
      expect(store.isProjectInActiveChain('pQ')).toBe(true)
    })

    it('setActiveRun does NOT add a terminal run to the election set', () => {
      store.setActiveRun(run('r6', ['pT'], 'completed'))
      expect(store.activeRun.id).toBe('r6')
      expect(store.isProjectInActiveChain('pT')).toBe(false)
    })

    it('fetchRun GETs the run and sets it active', async () => {
      api.sequenceRuns.get.mockResolvedValueOnce({ data: run('r7', ['pH'], 'running') })
      const r = await store.fetchRun('r7')
      expect(r.id).toBe('r7')
      expect(store.activeRun.id).toBe('r7')
      expect(api.sequenceRuns.get).toHaveBeenCalledWith('r7')
    })
  })

  describe('patchRun', () => {
    it('PATCHes and refreshes the cockpit run + election entry', async () => {
      store._testSetActiveRun(run('r1', ['pA'], 'running'))
      store._testSeedRuns([run('r1', ['pA'], 'running')])
      api.sequenceRuns.update.mockResolvedValueOnce({ data: run('r1', ['pA'], 'running', { execution_mode: 'subagent' }) })
      const updated = await store.patchRun('r1', { execution_mode: 'subagent' })
      expect(api.sequenceRuns.update).toHaveBeenCalledWith('r1', { execution_mode: 'subagent' })
      expect(updated.execution_mode).toBe('subagent')
      expect(store.activeRun.execution_mode).toBe('subagent')
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
    store._testSetActiveRun(run('r1', ['pA']))
    store.$reset()
    expect(store.activeRuns).toHaveLength(0)
    expect(store.activeRun).toBeNull()
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
    const activeRunData = run('r1', ['p1', 'p2'], 'running')
    store._testSeedRuns([activeRunData])
    store._testSetActiveRun(activeRunData)

    api.sequenceRuns.list.mockResolvedValueOnce({ data: [run('r1', ['p1', 'p2'], 'running', {
      project_statuses: { p1: 'completed', p2: 'implementing' },
    })] })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.isProjectInActiveChain('p1')).toBe(true)
    expect(store.isProjectInActiveChain('p2')).toBe(true)
    expect(store.activeRun?.project_statuses?.p1).toBe('completed')
    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
  })

  it('does fetch the terminal run when the whole run completes (genuine whole-run termination)', async () => {
    const activeRunData = run('r1', ['p1', 'p2'], 'running')
    store._testSeedRuns([activeRunData])
    store._testSetActiveRun(activeRunData)

    api.sequenceRuns.list.mockResolvedValueOnce({ data: [] })
    api.sequenceRuns.get.mockResolvedValueOnce({
      data: run('r1', ['p1', 'p2'], 'completed', { project_statuses: { p1: 'completed', p2: 'completed' } }),
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.isProjectInActiveChain('p1')).toBe(false)
    expect(api.sequenceRuns.get).toHaveBeenCalledWith('r1')
  })

  it('clears the stale activeRun and raises a retired-run notice when the run is genuinely gone', async () => {
    const activeRunData = run('r1', ['p1', 'p2'], 'running')
    store._testSeedRuns([activeRunData])
    store._testSetActiveRun(activeRunData)

    api.sequenceRuns.list.mockResolvedValueOnce({ data: [] })
    api.sequenceRuns.get.mockRejectedValueOnce({ response: { status: 404 } })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.activeRun).toBeNull()
    expect(store.retiredRunNotice).toEqual({ runId: 'r1' })
  })
})

describe('handleSequenceUpdated — chain staging live-fill (FE-6199)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('updates activeRun.chain_mission when conductor writes chain mission (still-active run)', async () => {
    const initial = run('r1', ['p1', 'p2'], 'pending', { chain_mission: null, locked: true })
    store._testSeedRuns([initial])
    store._testSetActiveRun(initial)

    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', {
        chain_mission: 'Build A then wire B',
        locked: true,
      })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.activeRun?.chain_mission).toBe('Build A then wire B')
    expect(store.isProjectInActiveChain('p1')).toBe(true)
    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
  })

  it('updates activeRun.locked to true when Stage Chain is pressed (still-active run)', async () => {
    const initial = run('r1', ['p1', 'p2'], 'pending', { locked: false, chain_mission: null })
    store._testSeedRuns([initial])
    store._testSetActiveRun(initial)

    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: null })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.activeRun?.locked).toBe(true)
  })

  it('arms chainImplementReady-relevant fields in one sequence:updated round-trip', async () => {
    const initial = run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: null })
    store._testSeedRuns([initial])
    store._testSetActiveRun(initial)

    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: 'Full delivery plan' })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.activeRun?.locked).toBe(true)
    expect(store.activeRun?.chain_mission).toBe('Full delivery plan')
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
