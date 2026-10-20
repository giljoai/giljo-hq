import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  launchChainHead: vi.fn(),
  stageChain: vi.fn(),
  unstageChain: vi.fn(),
  chainImplementation: vi.fn(),
  chainMemberFallback: vi.fn(),
  getDefault: vi.fn(),
  copy: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    prompts: {
      chainImplementation: (...a) => h.chainImplementation(...a),
      chainMemberFallback: (...a) => h.chainMemberFallback(...a),
    },
    settings: { getExecutionModeDefault: (...a) => h.getDefault(...a) },
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

import { flushPromises } from '@vue/test-utils'
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
  h.getDefault.mockResolvedValue({ data: { execution_mode_default: 'ask' } })
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

  it('reports a refused start without throwing, and copies nothing', async () => {
    h.launchChainHead.mockResolvedValue(false)
    const c = useChainGroupControls({ chainCtx: ctxFor() })
    await expect(c.handleChainImplement()).resolves.toBe(false)
    expect(c.launching.value).toBe(false)
    expect(h.chainImplementation).not.toHaveBeenCalled()
    expect(h.copy).not.toHaveBeenCalled()
  })

  it.each(['subagent', 'multi_terminal'])('%s: opens the head gate, then copies the chain prompt', async (mode) => {
    h.chainImplementation.mockResolvedValue({ data: { prompt: 'CONDUCTOR PROMPT' } })
    const c = useChainGroupControls({ chainCtx: ctxFor({ execution_mode: mode }) })
    await expect(c.handleChainImplement()).resolves.toBe(true)
    expect(h.launchChainHead).toHaveBeenCalledWith('head')
    expect(h.chainImplementation).toHaveBeenCalledWith('run-1')
    expect(h.launchChainHead.mock.invocationCallOrder[0]).toBeLessThan(h.chainImplementation.mock.invocationCallOrder[0])
    expect(h.copy).toHaveBeenCalledWith('CONDUCTOR PROMPT')
    expect(h.toast).toHaveBeenCalledWith({
      message: 'Chain prompt copied. Paste it into your conductor session.',
      type: 'success',
    })
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

  it('FE-9749: an unstaged chain with no mode needs one; a picked mode clears it', () => {
    const none = useChainGroupControls({ chainCtx: ctxFor({ locked: false, execution_mode: null }, { locked: false }) })
    expect(none.chainStageNeedsMode.value).toBe(true)
    expect(none.chainMode.value).toBeNull()
    const picked = useChainGroupControls({ chainCtx: ctxFor({ locked: false }, { locked: false }) })
    expect(picked.chainStageNeedsMode.value).toBe(false)
    expect(picked.chainMode.value).toBe('multi_terminal')
  })

  it('FE-9749: a real-mode account default is preselected; Stage writes it to the run first', async () => {
    h.getDefault.mockResolvedValue({ data: { execution_mode_default: 'subagent' } })
    const patch = vi.spyOn(store, 'patchRun').mockResolvedValue(null)
    const ctx = ctxFor({ locked: false, execution_mode: null }, { locked: false })
    const c = useChainGroupControls({ chainCtx: ctx })
    await flushPromises()
    expect(c.chainMode.value).toBe('subagent')
    expect(c.chainStageNeedsMode.value).toBe(false)
    expect(patch).not.toHaveBeenCalled()

    await c.handleChainStage()
    expect(patch).toHaveBeenCalledWith('run-1', { execution_mode: 'subagent' })
    expect(patch.mock.invocationCallOrder[0]).toBeLessThan(h.stageChain.mock.invocationCallOrder[0])
  })

  it('FE-9749: "Ask every time" preselects nothing', async () => {
    const c = useChainGroupControls({ chainCtx: ctxFor({ locked: false, execution_mode: null }, { locked: false }) })
    await flushPromises()
    expect(c.chainMode.value).toBeNull()
  })
})

describe('chainPhase (FE-9749)', () => {
  const tabs = [{ projectId: 'head' }, { projectId: 'tail' }]
  it('ready before staging, staged once locked', () => {
    expect(useChainGroupControls({ chainCtx: ctxFor({ locked: false }, { locked: false }) }).chainPhase.value).toBe('ready')
    expect(useChainGroupControls({ chainCtx: ctxFor() }).chainPhase.value).toBe('staged')
  })

  it('running with no agent past waiting is pickup; one agent working makes it running', () => {
    store._testSeedRuns([{ id: 'run-1', resolved_order: ['head', 'tail'], project_ids: ['head', 'tail'], status: 'running' }])
    const agents = { head: [{ status: 'waiting' }] }
    const ctx = ctxFor({ status: 'running' }, { tabs })
    const c = useChainGroupControls({ chainCtx: ctx, agentsByProject: () => agents })
    expect(c.chainPhase.value).toBe('pickup')
    agents.head = [{ status: 'working' }]
    expect(useChainGroupControls({ chainCtx: ctx, agentsByProject: () => agents }).chainPhase.value).toBe('running')
  })
})

describe('chainPhase reads the conductor (BE-9813)', () => {
  const tabs = [{ projectId: 'head' }, { projectId: 'tail' }]
  const waiting = () => ({ head: [{ status: 'waiting' }], tail: [] })

  it.each([
    ['working', 'running'],
    ['blocked', 'running'],
    ['complete', 'running'],
    ['waiting', 'pickup'],
    ['staged', 'pickup'],
    [null, 'pickup'],
    [undefined, 'pickup'],
  ])('conductor %s with every member waiting reads %s', (conductorStatus, phase) => {
    store._testSeedRuns([{ id: 'run-1', resolved_order: ['head', 'tail'], project_ids: ['head', 'tail'], status: 'running' }])
    const ctx = ctxFor({ status: 'running', conductor_status: conductorStatus }, { tabs })
    expect(useChainGroupControls({ chainCtx: ctx, agentsByProject: waiting }).chainPhase.value).toBe(phase)
  })
})

describe('prompt copies', () => {
  it('copies the conductor chain prompt verbatim', async () => {
    h.chainImplementation.mockResolvedValue({ data: { prompt: 'MASTER' } })
    await useChainGroupControls({ chainCtx: ctxFor() }).copyChainPrompt()
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
