import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  launchChainHead: vi.fn(),
  stageChain: vi.fn(),
  unstageChain: vi.fn(),
  chainImplementation: vi.fn(),
  chainMemberFallback: vi.fn(),
  copy: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    prompts: {
      chainImplementation: (...a) => h.chainImplementation(...a),
      chainMemberFallback: (...a) => h.chainMemberFallback(...a),
    },
  }
  return { default: api, api }
})
vi.mock('@/composables/useChainImplementation', () => ({
  useChainImplementation: () => ({ launchChainHead: h.launchChainHead }),
}))
vi.mock('@/composables/useChainLifecycle', () => ({
  useChainLifecycle: () => ({ stageChain: h.stageChain, unstageChain: h.unstageChain }),
}))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: h.copy }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.toast }) }))

import { useChainGroupControls } from './useChainGroupControls'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

function ctxFor(runOverrides = {}, extra = {}) {
  const run = {
    id: 'run-1',
    resolved_order: ['head', 'tail'],
    project_ids: ['tail', 'head'],
    status: 'pending',
    execution_mode: 'multi_terminal',
    chain_mission: 'Goal',
    project_statuses: {},
    locked: true,
    ...runOverrides,
  }
  return ref({ run, runId: run.id, locked: run.locked, tabs: [{ projectId: 'head' }], ...extra })
}

let store
beforeEach(() => {
  setActivePinia(createPinia())
  store = useSequenceRunStore()
  vi.clearAllMocks()
  h.launchChainHead.mockResolvedValue(true)
  h.copy.mockResolvedValue(true)
})

describe('Implement', () => {
  it('starts resolved_order[0], not project_ids[0]', async () => {
    const c = useChainGroupControls({ chainCtx: ctxFor() })
    await c.handleChainImplement()
    expect(h.launchChainHead).toHaveBeenCalledWith('head')
  })

  it('falls back to project_ids[0] when resolved_order is empty', async () => {
    const c = useChainGroupControls({ chainCtx: ctxFor({ resolved_order: [], project_ids: ['only'] }) })
    await c.handleChainImplement()
    expect(h.launchChainHead).toHaveBeenCalledWith('only')
  })

  it('reports a refused start without throwing', async () => {
    h.launchChainHead.mockResolvedValue(false)
    const c = useChainGroupControls({ chainCtx: ctxFor() })
    await expect(c.handleChainImplement()).resolves.toBe(false)
    expect(c.launching.value).toBe(false)
  })
})

describe('chainImplementReady (FE-6199 C1)', () => {
  const cases = [
    [{ status: 'pending' }, true],
    [{ status: 'staged' }, true],
    [{ status: 'running' }, false],
    [{ status: 'completed' }, false],
    [{ locked: false }, false],
    [{ chain_mission: '' }, false],
    [{ chain_mission: '   ' }, false],
    [{ chain_mission: null }, false],
  ]
  it.each(cases)('run %o -> %s', (overrides, expected) => {
    const chainCtx = ctxFor(overrides)
    chainCtx.value.locked = chainCtx.value.run.locked
    const c = useChainGroupControls({ chainCtx })
    expect(c.chainImplementReady.value).toBe(expected)
  })

  it('is false without a chain', () => {
    const c = useChainGroupControls({ chainCtx: ref(null) })
    expect(c.chainImplementReady.value).toBe(false)
  })
})

describe('Stage / mode', () => {
  it('Stage locks an unlocked chain; Unstage unlocks a locked one', async () => {
    const unlocked = ctxFor({ locked: false }, { locked: false })
    await useChainGroupControls({ chainCtx: unlocked }).handleChainStage()
    expect(h.stageChain).toHaveBeenCalledWith(unlocked.value.run)
    await useChainGroupControls({ chainCtx: ctxFor() }).handleChainStage()
    expect(h.unstageChain).toHaveBeenCalled()
  })

  it('patches the mode on the run only while unlocked', async () => {
    const patch = vi.spyOn(store, 'patchRun').mockResolvedValue(null)
    await useChainGroupControls({ chainCtx: ctxFor() }).patchRunMode('subagent')
    expect(patch).not.toHaveBeenCalled()
    await useChainGroupControls({ chainCtx: ctxFor({ locked: false }, { locked: false }) }).patchRunMode('subagent')
    expect(patch).toHaveBeenCalledWith('run-1', { execution_mode: 'subagent' })
  })

  it('offers the master prompt only for a staged multi-terminal chain that is not running', () => {
    expect(useChainGroupControls({ chainCtx: ctxFor() }).showCopyMasterPrompt.value).toBe(true)
    expect(
      useChainGroupControls({ chainCtx: ctxFor({ execution_mode: 'subagent' }) }).showCopyMasterPrompt.value,
    ).toBe(false)
    expect(
      useChainGroupControls({ chainCtx: ctxFor({ locked: false }, { locked: false }) }).showCopyMasterPrompt.value,
    ).toBe(false)
  })
})

describe('prompt copies', () => {
  it('copies the conductor prompt verbatim', async () => {
    h.chainImplementation.mockResolvedValue({ data: { prompt: 'MASTER' } })
    await useChainGroupControls({ chainCtx: ctxFor() }).copyMasterPrompt()
    expect(h.chainImplementation).toHaveBeenCalledWith('run-1')
    expect(h.copy).toHaveBeenCalledWith('MASTER')
  })

  it('copies a member fallback prompt verbatim and surfaces a refusal', async () => {
    h.chainMemberFallback.mockResolvedValueOnce({ data: { prompt: 'FALLBACK' } })
    const c = useChainGroupControls({ chainCtx: ctxFor() })
    await c.copyMemberFallbackPrompt('tail')
    expect(h.copy).toHaveBeenCalledWith('FALLBACK')

    h.chainMemberFallback.mockRejectedValueOnce({
      response: { status: 400, data: { error_code: 'VALIDATIONERROR', message: 'Stage the chain first.' } },
    })
    await c.copyMemberFallbackPrompt('tail')
    expect(h.toast).toHaveBeenLastCalledWith(expect.objectContaining({ message: 'Stage the chain first.', type: 'error' }))
  })
})

describe('Stop chain (FE-9632)', () => {
  it('opens the confirm first and stops only on confirm', async () => {
    const stop = vi.spyOn(store, 'stopChain').mockResolvedValue({})
    const c = useChainGroupControls({ chainCtx: ctxFor({ status: 'running' }) })
    c.openChainStopConfirm()
    expect(c.showChainStopConfirm.value).toBe(true)
    expect(stop).not.toHaveBeenCalled()
    await c.handleChainStop()
    expect(stop).toHaveBeenCalledWith('run-1')
    expect(c.showChainStopConfirm.value).toBe(false)
  })

  it('a failed stop keeps the modal, toasts, and clears its in-flight flag', async () => {
    vi.spyOn(store, 'stopChain').mockRejectedValue(new Error('boom'))
    const c = useChainGroupControls({ chainCtx: ctxFor({ status: 'running' }) })
    c.openChainStopConfirm()
    await c.handleChainStop()
    expect(c.showChainStopConfirm.value).toBe(true)
    expect(c.chainStopping.value).toBe(false)
    expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
  })
})

describe('Deactivate chain', () => {
  it('posts the rewind through the store only on confirm', async () => {
    const deactivate = vi.spyOn(store, 'deactivateChain').mockResolvedValue()
    const c = useChainGroupControls({ chainCtx: ctxFor() })
    c.openDeactivateConfirm()
    expect(deactivate).not.toHaveBeenCalled()
    await c.handleChainDeactivate()
    expect(deactivate).toHaveBeenCalledWith('run-1')
    expect(c.showDeactivateConfirm.value).toBe(false)
  })

  it('cancel closes the confirm without deactivating', () => {
    const deactivate = vi.spyOn(store, 'deactivateChain')
    const c = useChainGroupControls({ chainCtx: ctxFor() })
    c.openDeactivateConfirm()
    c.cancelDeactivate()
    expect(c.showDeactivateConfirm.value).toBe(false)
    expect(deactivate).not.toHaveBeenCalled()
  })
})
