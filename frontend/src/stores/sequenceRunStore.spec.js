/**
 * sequenceRunStore.spec.js — FE-6165f
 *
 * Durable-election keystone: hydrate from the bare-array list, the three
 * membership getters, PATCH/terminal-drop, and the WS re-fetch handler.
 */
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
      // FE-9104: hydrate now also requests terminal review-pending runs so the
      // chain review surface stays reachable after a cold refresh.
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
      // r2 went terminal → no longer returned by the status filter
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
      // After the event, r2 has gone terminal → dropped from the list
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

// UI-2 / BE-6177: per-member archive must NOT eject the user from the chain view.
// handleSequenceUpdated re-hydrates on sequence:updated. If the run is STILL active
// (status=running, present in hydrate list), runsById keeps it → no fetchRun fallback
// → activeRun stays pointed at the active run → no eject.
describe('handleSequenceUpdated — chain eject guard (UI-2)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('does NOT eject when a member closes but the run stays active (still in hydrate list)', async () => {
    // Seed one active run as the cockpit's open run.
    const activeRunData = run('r1', ['p1', 'p2'], 'running')
    store._testSeedRuns([activeRunData])
    store._testSetActiveRun(activeRunData)

    // After the member-close sequence:updated, hydrate still returns the run
    // (still running — conductor hasn't finished the whole chain yet).
    api.sequenceRuns.list.mockResolvedValueOnce({ data: [run('r1', ['p1', 'p2'], 'running', {
      project_statuses: { p1: 'completed', p2: 'implementing' },
    })] })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    // Run must remain in the active set (no fetchRun fallback triggered).
    expect(store.isProjectInActiveChain('p1')).toBe(true)
    expect(store.isProjectInActiveChain('p2')).toBe(true)
    // activeRun is updated with the fresh data from hydrate (p1 now completed).
    expect(store.activeRun?.project_statuses?.p1).toBe('completed')
    // fetchRun is NOT called (the fallback path for a terminal run).
    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
  })

  it('does fetch the terminal run when the whole run completes (genuine whole-run termination)', async () => {
    // Seed one active run as open in the cockpit.
    const activeRunData = run('r1', ['p1', 'p2'], 'running')
    store._testSeedRuns([activeRunData])
    store._testSetActiveRun(activeRunData)

    // After the conductor completes the chain, hydrate returns NOTHING (run is terminal).
    api.sequenceRuns.list.mockResolvedValueOnce({ data: [] })
    // fetchRun returns the terminal snapshot for the cockpit to display.
    api.sequenceRuns.get.mockResolvedValueOnce({
      data: run('r1', ['p1', 'p2'], 'completed', { project_statuses: { p1: 'completed', p2: 'completed' } }),
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    // Run dropped from the active set.
    expect(store.isProjectInActiveChain('p1')).toBe(false)
    // fetchRun WAS called to give the cockpit the terminal snapshot.
    expect(api.sequenceRuns.get).toHaveBeenCalledWith('r1')
  })

  // BE-9540: the run purged out from under an OPEN cockpit (conductor finale
  // deleted the row, not just retired its status). Before the fix, fetchRun's
  // 404 was swallowed with "leave last-known activeRun in place" — the cockpit
  // kept showing a Review card for a run that no longer exists, and any further
  // interaction (e.g. clicking review) would storm more 404s against it.
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

// FE-6199: chain staging live-fill — conductor writes chain_mission →
// sequence:updated → handleSequenceUpdated must update activeRun.chain_mission
// and activeRun.locked so useChainContext watchers fire and chainImplementReady arms.
describe('handleSequenceUpdated — chain staging live-fill (FE-6199)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('updates activeRun.chain_mission when conductor writes chain mission (still-active run)', async () => {
    // Cockpit open: run is pending, chain_mission not yet written.
    const initial = run('r1', ['p1', 'p2'], 'pending', { chain_mission: null, locked: true })
    store._testSeedRuns([initial])
    store._testSetActiveRun(initial)

    // After the conductor writes chain_mission, hydrate returns the updated run.
    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', {
        chain_mission: 'Build A then wire B',
        locked: true,
      })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    // activeRun must reflect the freshly written chain_mission.
    expect(store.activeRun?.chain_mission).toBe('Build A then wire B')
    // Run stays in the active set (still pending).
    expect(store.isProjectInActiveChain('p1')).toBe(true)
    // No extra GET /sequence-runs/:id — data came from the list.
    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
  })

  it('updates activeRun.locked to true when Stage Chain is pressed (still-active run)', async () => {
    const initial = run('r1', ['p1', 'p2'], 'pending', { locked: false, chain_mission: null })
    store._testSeedRuns([initial])
    store._testSetActiveRun(initial)

    // After Stage Chain, hydrate returns locked: true.
    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: null })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(store.activeRun?.locked).toBe(true)
  })

  it('arms chainImplementReady-relevant fields in one sequence:updated round-trip', async () => {
    // Start: staged run, locked, no mission yet.
    const initial = run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: null })
    store._testSeedRuns([initial])
    store._testSetActiveRun(initial)

    // Conductor writes mission: hydrate returns locked + mission.
    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [run('r1', ['p1', 'p2'], 'pending', { locked: true, chain_mission: 'Full delivery plan' })],
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    // Both fields that chainImplementReady reads must be fresh.
    expect(store.activeRun?.locked).toBe(true)
    expect(store.activeRun?.chain_mission).toBe('Full delivery plan')
    // The run is still active — no fetchRun needed.
    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
  })
})
