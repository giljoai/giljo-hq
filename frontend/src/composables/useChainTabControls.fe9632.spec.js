import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const { mockShowToast } = vi.hoisted(() => ({ mockShowToast: vi.fn() }))

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: mockShowToast }) }))
vi.mock('@/composables/useChainImplementation', () => ({
  useChainImplementation: () => ({ launchChainHead: vi.fn(() => Promise.resolve(true)) }),
}))
vi.mock('@/composables/useChainLifecycle', () => ({
  useChainLifecycle: () => ({ stageChain: vi.fn(), unstageChain: vi.fn() }),
}))

import { useChainTabControls } from './useChainTabControls'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

const makeCtx = (runOverrides = {}) => ({
  run: {
    id: 'run-1',
    status: 'pending',
    resolved_order: ['p1', 'p2'],
    project_ids: ['p1', 'p2'],
    project_statuses: { p1: 'pending', p2: 'pending' },
    execution_mode: 'subagent',
    ...runOverrides,
  },
  runId: 'run-1',
  tabs: [{ projectId: 'p1' }, { projectId: 'p2' }],
  locked: true,
})

const stubRouter = () => ({ push: vi.fn(), replace: vi.fn() })

describe('useChainTabControls FE-9632 — member card click routing', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockShowToast.mockClear()
  })

  it('forces tab=jobs once the chain is running', () => {
    const store = useSequenceRunStore()
    vi.spyOn(store, 'isRunning').mockReturnValue(true)
    const router = stubRouter()
    const { handleTabSelect } = useChainTabControls({
      chainCtx: ref(makeCtx({ status: 'running' })),
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1', tab: 'launch' } },
      activeTab: ref('launch'),
    })

    handleTabSelect('p2')

    expect(router.push).toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ tab: 'jobs' }) }),
    )
  })

  it('keeps carrying ?run when it forces tab=jobs (the chain layer must survive)', () => {
    const store = useSequenceRunStore()
    vi.spyOn(store, 'isRunning').mockReturnValue(true)
    const router = stubRouter()
    const { handleTabSelect } = useChainTabControls({
      chainCtx: ref(makeCtx({ status: 'running' })),
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1', tab: 'launch' } },
      activeTab: ref('launch'),
    })

    handleTabSelect('p2')

    expect(router.push.mock.calls[0][0].query.run).toBe('run-1')
  })

  it('keeps TODAY\'s carry-the-tab behaviour before the chain is running', () => {
    const store = useSequenceRunStore()
    vi.spyOn(store, 'isRunning').mockReturnValue(false)
    const router = stubRouter()
    const { handleTabSelect } = useChainTabControls({
      chainCtx: ref(makeCtx()),
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1', tab: 'launch' } },
      activeTab: ref('launch'),
    })

    handleTabSelect('p2')

    expect(router.push.mock.calls[0][0].query.tab).toBe('launch')
  })

  it('is still a no-op when the clicked card is the one already open', () => {
    const store = useSequenceRunStore()
    vi.spyOn(store, 'isRunning').mockReturnValue(true)
    const router = stubRouter()
    const { handleTabSelect } = useChainTabControls({
      chainCtx: ref(makeCtx({ status: 'running' })),
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1', tab: 'launch' } },
      activeTab: ref('launch'),
    })

    handleTabSelect('p1')

    expect(router.push).not.toHaveBeenCalled()
  })
})

describe('useChainTabControls FE-9632 — Stop chain', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockShowToast.mockClear()
  })

  function setup(runOverrides = {}) {
    const store = useSequenceRunStore()
    const stopChain = vi.spyOn(store, 'stopChain').mockResolvedValue({ id: 'run-1', status: 'cancelled' })
    const router = stubRouter()
    const controls = useChainTabControls({
      chainCtx: ref(makeCtx({ status: 'running', ...runOverrides })),
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1', tab: 'jobs' } },
      activeTab: ref('jobs'),
    })
    return { controls, router, stopChain }
  }

  it('opens the confirm modal without stopping anything yet', () => {
    const { controls, stopChain } = setup()

    controls.openChainStopConfirm()

    expect(controls.showChainStopConfirm.value).toBe(true)
    expect(stopChain).not.toHaveBeenCalled()
  })

  it('cancelling closes the modal and stops nothing', async () => {
    const { controls, router, stopChain } = setup()
    controls.openChainStopConfirm()

    controls.cancelChainStop()

    expect(controls.showChainStopConfirm.value).toBe(false)
    expect(stopChain).not.toHaveBeenCalled()
    expect(router.push).not.toHaveBeenCalled()
  })

  it('confirming calls the store stop action for this run', async () => {
    const { controls, stopChain } = setup()

    await controls.handleChainStop()

    expect(stopChain).toHaveBeenCalledWith('run-1')
  })

  it('confirming toasts "Chain stopped." and leaves for the Projects list', async () => {
    const { controls, router } = setup()

    await controls.handleChainStop()

    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Chain stopped.' }),
    )
    expect(router.push).toHaveBeenCalledWith(expect.objectContaining({ name: 'Projects' }))
  })

  it('a failed stop surfaces an error toast and does NOT navigate away', async () => {
    const store = useSequenceRunStore()
    vi.spyOn(store, 'stopChain').mockRejectedValue(new Error('nope'))
    const router = stubRouter()
    const controls = useChainTabControls({
      chainCtx: ref(makeCtx({ status: 'running' })),
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1', tab: 'jobs' } },
      activeTab: ref('jobs'),
    })

    await controls.handleChainStop()

    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    expect(router.push).not.toHaveBeenCalled()
  })

  it('clears its in-flight flag after a failure so the button is not stuck', async () => {
    const store = useSequenceRunStore()
    vi.spyOn(store, 'stopChain').mockRejectedValue(new Error('nope'))
    const controls = useChainTabControls({
      chainCtx: ref(makeCtx({ status: 'running' })),
      projectId: ref('p1'),
      router: stubRouter(),
      route: { query: { run: 'run-1', tab: 'jobs' } },
      activeTab: ref('jobs'),
    })

    await controls.handleChainStop()

    expect(controls.chainStopping.value).toBe(false)
  })
})
