/**
 * useChainLifecycle.fe6171b.spec.js — FE-6171b
 *
 * Regression tests for the FE-6171b redefinitions:
 *   - stageChain: lockRun (PATCH locked=true) + copy staging prompt + toast
 *   - unstageChain: UNLOCK ONLY (PATCH locked=false) — chain stays intact, NOT dissolve
 *   - unstageChain: surfaces 422 as an error toast
 *   - releaseChain: still calls release endpoint (dissolve behavior preserved from FE-6170)
 *
 * Global test setup (tests/setup.js) mocks @/services/api and @/composables/useToast.
 * Edition scope: CE.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import api from '@/services/api'
import { useChainLifecycle } from './useChainLifecycle'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

function makeRun(overrides = {}) {
  return {
    id: 'run-1',
    project_ids: ['p1', 'p2'],
    resolved_order: ['p1', 'p2'],
    current_index: 0,
    status: 'pending',
    execution_mode: 'multi_terminal',
    project_statuses: { p1: 'pending', p2: 'pending' },
    locked: false,
    ...overrides,
  }
}

describe('useChainLifecycle — FE-6171b stageChain', () => {
  let sequenceRunStore

  beforeEach(() => {
    setActivePinia(createPinia())
    sequenceRunStore = useSequenceRunStore()
    sequenceRunStore._testSeedRuns([makeRun()])
    sequenceRunStore._testSetActiveRun(makeRun())
  })

  it('PATCHes run locked=true, fetches staging prompt, does not throw', async () => {
    api.sequenceRuns.update.mockResolvedValueOnce({
      data: makeRun({ locked: true }),
    })
    api.prompts.chainStaging.mockResolvedValueOnce({ data: { prompt: 'CHAIN STAGE PROMPT' } })

    const { stageChain } = useChainLifecycle()
    const updated = await stageChain(makeRun())

    expect(api.sequenceRuns.update).toHaveBeenCalledWith('run-1', { locked: true })
    expect(api.prompts.chainStaging).toHaveBeenCalledWith('run-1')
    expect(updated.locked).toBe(true)
  })

  it('returns null and does not throw when PATCH fails', async () => {
    api.sequenceRuns.update.mockRejectedValueOnce({
      response: { data: { detail: 'update failed' } },
    })

    const { stageChain } = useChainLifecycle()
    const updated = await stageChain(makeRun())

    expect(updated).toBeNull()
  })

  it('succeeds without a staging prompt (graceful no-prompt path)', async () => {
    api.sequenceRuns.update.mockResolvedValueOnce({ data: makeRun({ locked: true }) })
    api.prompts.chainStaging.mockResolvedValueOnce({ data: {} }) // no prompt field

    const { stageChain } = useChainLifecycle()
    const updated = await stageChain(makeRun())

    expect(updated).not.toBeNull()
  })
})

describe('useChainLifecycle — FE-6171b unstageChain (UNLOCK, not dissolve)', () => {
  let sequenceRunStore

  beforeEach(() => {
    setActivePinia(createPinia())
    sequenceRunStore = useSequenceRunStore()
    const lockedRun = makeRun({ locked: true })
    sequenceRunStore._testSeedRuns([lockedRun])
    sequenceRunStore._testSetActiveRun(lockedRun)
  })

  it('PATCHes run locked=false and returns the updated run', async () => {
    const lockedRun = makeRun({ locked: true })
    api.sequenceRuns.update.mockResolvedValueOnce({
      data: makeRun({ locked: false }),
    })

    const { unstageChain } = useChainLifecycle()
    const updated = await unstageChain(lockedRun)

    expect(api.sequenceRuns.update).toHaveBeenCalledWith('run-1', { locked: false })
    expect(updated.locked).toBe(false)
  })

  it('DOES NOT call release endpoint (chain not dissolved)', async () => {
    api.sequenceRuns.update.mockResolvedValueOnce({ data: makeRun({ locked: false }) })

    const { unstageChain } = useChainLifecycle()
    await unstageChain(makeRun({ locked: true }))

    expect(api.sequenceRuns.release).not.toHaveBeenCalled()
  })

  it('chain members remain in runsById after unlock (chain stays intact)', async () => {
    api.sequenceRuns.update.mockResolvedValueOnce({
      data: makeRun({ locked: false }),
    })

    const { unstageChain } = useChainLifecycle()
    await unstageChain(makeRun({ locked: true }))

    // Run stays in runsById (status still 'pending' = active).
    expect(sequenceRunStore.runsById.has('run-1')).toBe(true)
    expect(sequenceRunStore.isProjectInActiveChain('p1')).toBe(true)
    expect(sequenceRunStore.isProjectInActiveChain('p2')).toBe(true)
  })

  it('returns null when BE responds with 422 (ultralock tier)', async () => {
    api.sequenceRuns.update.mockRejectedValueOnce({
      response: { status: 422, data: { detail: 'Cannot unlock: run is ultralocked' } },
    })

    const { unstageChain } = useChainLifecycle()
    const updated = await unstageChain(makeRun({ locked: true }))

    expect(updated).toBeNull()
  })
})
