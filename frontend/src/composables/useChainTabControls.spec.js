import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const { mockCopyImplPrompt, mockShowToast } = vi.hoisted(() => ({
  mockCopyImplPrompt: vi.fn(() => Promise.resolve(true)),
  mockShowToast: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: mockShowToast }) }))
vi.mock('@/composables/useChainImplementation', () => ({
  useChainImplementation: () => ({ copyImplPrompt: mockCopyImplPrompt }),
}))
vi.mock('@/composables/useChainLifecycle', () => ({
  useChainLifecycle: () => ({ stageChain: vi.fn(), unstageChain: vi.fn() }),
}))

import { useChainTabControls } from './useChainTabControls'

const makeChainCtx = (overrides = {}) => ({
  run: { id: 'run-1', resolved_order: ['head-pid', 'b-pid'], project_ids: ['head-pid', 'b-pid'] },
  runId: 'run-1',
  tabs: [{ projectId: 'head-pid' }, { projectId: 'b-pid' }],
  locked: true,
  ...overrides,
})

const makeReadyCtx = (runOverrides = {}, ctxOverrides = {}) => ({
  run: {
    id: 'run-1',
    status: 'pending',
    resolved_order: ['p1', 'p2'],
    project_ids: ['p1', 'p2'],
    project_statuses: { p1: 'pending', p2: 'pending' },
    chain_mission: 'Deliver the feature',
    ...runOverrides,
  },
  runId: 'run-1',
  tabs: [{ projectId: 'p1' }, { projectId: 'p2' }],
  locked: true,
  ...ctxOverrides,
})

const stubRouter = () => ({ push: vi.fn(), replace: vi.fn() })

describe('useChainTabControls — Implement wiring (BE-6177)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockCopyImplPrompt.mockClear()
    mockCopyImplPrompt.mockResolvedValue(true)
    mockShowToast.mockClear()
  })

  it('passes the head project id (resolved_order[0]) to copyImplPrompt', async () => {
    const chainCtx = ref(makeChainCtx())
    const { handleChainImplement } = useChainTabControls({
      chainCtx,
      projectId: ref('head-pid'),
      router: stubRouter(),
      route: { query: {} },
      activeTab: ref('launch'),
    })

    await handleChainImplement()

    expect(mockCopyImplPrompt).toHaveBeenCalledWith('run-1', 'head-pid')
  })

  it('falls back to project_ids[0] when resolved_order is absent', async () => {
    const chainCtx = ref(makeChainCtx({
      run: { id: 'run-1', project_ids: ['fallback-head', 'b-pid'] },
    }))
    const { handleChainImplement } = useChainTabControls({
      chainCtx,
      projectId: ref('fallback-head'),
      router: stubRouter(),
      route: { query: {} },
    })

    await handleChainImplement()

    expect(mockCopyImplPrompt).toHaveBeenCalledWith('run-1', 'fallback-head')
  })

  it('flips activeTab to jobs after a SUCCESSFUL Implement (Bug 2 solo parity)', async () => {
    mockCopyImplPrompt.mockResolvedValueOnce(true)
    const activeTab = ref('launch')
    const router = stubRouter()
    const { handleChainImplement } = useChainTabControls({
      chainCtx: ref(makeChainCtx()),
      projectId: ref('head-pid'),
      router,
      route: { query: {} },
      activeTab,
    })

    await handleChainImplement()

    expect(activeTab.value).toBe('jobs')
    expect(router.replace).toHaveBeenCalledWith({ query: { via: 'jobs' } })
  })

  it('leaves activeTab on launch when the Implement copy fails', async () => {
    mockCopyImplPrompt.mockResolvedValueOnce(false)
    const activeTab = ref('launch')
    const router = stubRouter()
    const { handleChainImplement } = useChainTabControls({
      chainCtx: ref(makeChainCtx()),
      projectId: ref('head-pid'),
      router,
      route: { query: {} },
      activeTab,
    })

    await handleChainImplement()

    expect(activeTab.value).toBe('launch')
    expect(router.replace).not.toHaveBeenCalled()
  })
})

describe('useChainTabControls — chainImplementReady gate (FE-6199 C1)', () => {
  function build(ctx) {
    return useChainTabControls({
      chainCtx: ref(ctx),
      projectId: ref('p1'),
      router: stubRouter(),
      route: { query: {} },
    })
  }

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('true when pending + locked + mission (members NOT yet staging_complete)', () => {
    const { chainImplementReady } = build(makeReadyCtx())
    expect(chainImplementReady.value).toBe(true)
  })

  it("true when status is 'staged' (the other pre-implementation state)", () => {
    const { chainImplementReady } = build(makeReadyCtx({ status: 'staged' }))
    expect(chainImplementReady.value).toBe(true)
  })

  it('false when status is running (already started)', () => {
    const { chainImplementReady } = build(makeReadyCtx({ status: 'running' }))
    expect(chainImplementReady.value).toBe(false)
  })

  it('false when status is implementing (already started)', () => {
    const { chainImplementReady } = build(makeReadyCtx({ status: 'implementing' }))
    expect(chainImplementReady.value).toBe(false)
  })

  it('false when status is completed (finished run)', () => {
    const { chainImplementReady } = build(makeReadyCtx({ status: 'completed' }))
    expect(chainImplementReady.value).toBe(false)
  })

  it('false when status is terminated (finished run)', () => {
    const { chainImplementReady } = build(makeReadyCtx({ status: 'terminated' }))
    expect(chainImplementReady.value).toBe(false)
  })

  it('false when locked is false (not staged)', () => {
    const { chainImplementReady } = build(makeReadyCtx({}, { locked: false }))
    expect(chainImplementReady.value).toBe(false)
  })

  it('false when chain_mission is empty', () => {
    const { chainImplementReady } = build(makeReadyCtx({ chain_mission: '' }))
    expect(chainImplementReady.value).toBe(false)
  })

  it('false when chain_mission is null', () => {
    const { chainImplementReady } = build(makeReadyCtx({ chain_mission: null }))
    expect(chainImplementReady.value).toBe(false)
  })

  it('false when chain_mission is whitespace-only', () => {
    const { chainImplementReady } = build(makeReadyCtx({ chain_mission: '   ' }))
    expect(chainImplementReady.value).toBe(false)
  })

  it('false when chainCtx is null (solo)', () => {
    const { chainImplementReady } = build(null)
    expect(chainImplementReady.value).toBe(false)
  })
})

describe('useChainTabControls — handleChainReviewComplete (UI-2)', () => {
  let mockPatchRun

  beforeEach(() => {
    setActivePinia(createPinia())
    mockCopyImplPrompt.mockClear()
    mockShowToast.mockClear()
  })

  it('hides the modal and does NOT call patchRun', async () => {
    const { useSequenceRunStore } = await import('@/stores/sequenceRunStore')
    const sequenceRunStore = useSequenceRunStore()
    mockPatchRun = vi.spyOn(sequenceRunStore, 'patchRun')

    const chainCtx = ref({
      run: { id: 'run-1', project_statuses: { p1: 'implementing', p2: 'implementing' }, resolved_order: ['p1', 'p2'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', isCompleted: false, status: 'implementing' },
        { projectId: 'p2', isCompleted: false, status: 'implementing' },
      ],
      locked: true,
    })

    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx,
      projectId: ref('p1'),
      router: stubRouter(),
      route: { query: {} },
    })

    chainReviewTab.value = { projectId: 'p1', name: 'Project 1', isCompleted: false }
    showChainReview.value = true

    await handleChainReviewComplete()

    expect(showChainReview.value).toBe(false)
    expect(mockPatchRun).not.toHaveBeenCalled()
  })

  it('calls markReviewed with the reviewed runId + pid', async () => {
    const { useSequenceRunStore } = await import('@/stores/sequenceRunStore')
    const sequenceRunStore = useSequenceRunStore()
    const mockMark = vi.spyOn(sequenceRunStore, 'markReviewed')

    const chainCtx = ref({
      run: { id: 'run-1', resolved_order: ['p1', 'p2'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', isCompleted: true, status: 'completed' },
        { projectId: 'p2', isCompleted: true, status: 'completed' },
      ],
      locked: true,
    })

    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx,
      projectId: ref('p1'),
      router: stubRouter(),
      route: { query: {} },
    })

    chainReviewTab.value = { projectId: 'p1', name: 'P1', isCompleted: true }
    showChainReview.value = true

    await handleChainReviewComplete()

    expect(mockMark).toHaveBeenCalledWith('run-1', 'p1')
  })
})

describe('useChainTabControls — handleChainReviewComplete persistence (BE-9098)', () => {
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

  beforeEach(() => {
    setActivePinia(createPinia())
    mockCopyImplPrompt.mockClear()
    mockShowToast.mockClear()
  })

  const reviewCtx = () =>
    ref({
      run: { id: 'run-1', resolved_order: ['p1', 'p2'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', isCompleted: true, status: 'completed' },
        { projectId: 'p2', isCompleted: false, status: 'implementing' },
      ],
      locked: true,
    })

  it('calls markReviewedRemote with the reviewed runId + pid (durable persist)', async () => {
    const { useSequenceRunStore } = await import('@/stores/sequenceRunStore')
    const sequenceRunStore = useSequenceRunStore()
    const mockRemote = vi.spyOn(sequenceRunStore, 'markReviewedRemote').mockResolvedValue({})

    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx: reviewCtx(),
      projectId: ref('p1'),
      router: stubRouter(),
      route: { query: {} },
    })
    chainReviewTab.value = { projectId: 'p1', name: 'P1', isCompleted: true }
    showChainReview.value = true

    await handleChainReviewComplete()
    await flush()

    expect(mockRemote).toHaveBeenCalledWith('run-1', 'p1')
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('surfaces a toast when the durable persist fails (non-gating; optimistic mark stays)', async () => {
    const { useSequenceRunStore } = await import('@/stores/sequenceRunStore')
    const sequenceRunStore = useSequenceRunStore()
    vi.spyOn(sequenceRunStore, 'markReviewedRemote').mockRejectedValue(new Error('boom'))

    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx: reviewCtx(),
      projectId: ref('p1'),
      router: stubRouter(),
      route: { query: {} },
    })
    chainReviewTab.value = { projectId: 'p1', name: 'P1', isCompleted: true }
    showChainReview.value = true

    await handleChainReviewComplete()
    await flush()

    expect(mockShowToast).toHaveBeenCalledTimes(1)
    expect(sequenceRunStore.isReviewed('run-1', 'p1')).toBe(true)
  })
})

describe('useChainTabControls — handleChainReviewComplete advance/return', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockCopyImplPrompt.mockClear()
    mockShowToast.mockClear()
  })

  it('non-last chain review does NOT navigate while a later member is still WORKING', async () => {
    const router = stubRouter()
    const chainCtx = ref({
      run: { id: 'run-1', project_statuses: {}, resolved_order: ['p1', 'p2'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', name: 'P1', isCompleted: true, status: 'completed' },
        { projectId: 'p2', name: 'P2', isCompleted: false, status: 'implementing' },
      ],
      locked: true,
    })
    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx,
      projectId: ref('p1'),
      router,
      route: { query: {} },
    })
    chainReviewTab.value = { projectId: 'p1', name: 'P1', isCompleted: true }
    showChainReview.value = true

    await handleChainReviewComplete()

    expect(router.push).not.toHaveBeenCalled()
    expect(router.push).not.toHaveBeenCalledWith('/projects')
  })

  it('final review (every member completed AND reviewed) DOES navigate to /projects', async () => {
    const router = stubRouter()
    const chainCtx = ref({
      run: { id: 'run-1', project_statuses: {}, resolved_order: ['p1', 'p2'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', name: 'P1', isCompleted: true, status: 'completed' },
        { projectId: 'p2', name: 'P2', isCompleted: true, status: 'completed' },
      ],
      locked: true,
    })
    const { useSequenceRunStore } = await import('@/stores/sequenceRunStore')
    const seqStore = useSequenceRunStore()
    seqStore.markReviewed('run-1', 'p1')

    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx,
      projectId: ref('p2'),
      router,
      route: { query: {} },
    })
    chainReviewTab.value = { projectId: 'p2', name: 'P2', isCompleted: true }
    showChainReview.value = true

    await handleChainReviewComplete()

    expect(router.push).toHaveBeenCalledWith('/projects')
  })

  it('3-member walk with a working tail stays in /jobs', async () => {
    const router = stubRouter()
    const chainCtx = ref({
      run: { id: 'run-1', project_statuses: {}, resolved_order: ['p1', 'p2', 'p3'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', name: 'P1', isCompleted: true, status: 'completed' },
        { projectId: 'p2', name: 'P2', isCompleted: true, status: 'completed' },
        { projectId: 'p3', name: 'P3', isCompleted: false, status: 'implementing' },
      ],
      locked: true,
    })

    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx,
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1' } },
    })

    chainReviewTab.value = { projectId: 'p1', name: 'P1', isCompleted: true }
    showChainReview.value = true
    await handleChainReviewComplete()
    expect(router.push).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'p2' },
      query: { run: 'run-1' },
    })

    router.push.mockClear()

    chainReviewTab.value = { projectId: 'p2', name: 'P2', isCompleted: true }
    showChainReview.value = true
    await handleChainReviewComplete()
    expect(router.push).not.toHaveBeenCalled()
  })

  it('advances to the next UNREVIEWED completed tab when one remains', async () => {
    const router = stubRouter()
    const chainCtx = ref({
      run: { id: 'run-1', project_statuses: {}, resolved_order: ['p1', 'p2'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', name: 'P1', isCompleted: true, status: 'completed' },
        { projectId: 'p2', name: 'P2', isCompleted: true, status: 'completed' },
      ],
      locked: true,
    })
    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx,
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1' } },
    })
    chainReviewTab.value = { projectId: 'p1', name: 'P1', isCompleted: true }
    showChainReview.value = true

    await handleChainReviewComplete()

    expect(showChainReview.value).toBe(false)
    expect(router.push).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'p2' },
      query: { run: 'run-1' },
    })
  })

  it('navigates to /projects after the last UNREVIEWED completed member is confirmed', async () => {
    const router = stubRouter()
    const chainCtx = ref({
      run: { id: 'run-1', project_statuses: {}, resolved_order: ['p1', 'p2'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', name: 'P1', isCompleted: true, status: 'completed' },
        { projectId: 'p2', name: 'P2', isCompleted: true, status: 'completed' },
      ],
      locked: true,
    })
    const { useSequenceRunStore } = await import('@/stores/sequenceRunStore')
    const seqStore = useSequenceRunStore()
    seqStore.markReviewed('run-1', 'p1')

    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx,
      projectId: ref('p2'),
      router,
      route: { query: {} },
    })
    chainReviewTab.value = { projectId: 'p2', name: 'P2', isCompleted: true }
    showChainReview.value = true

    await handleChainReviewComplete()

    expect(showChainReview.value).toBe(false)
    expect(router.push).toHaveBeenCalledWith('/projects')
  })

  it('skips already-reviewed tabs and jumps to the first genuinely unreviewed', async () => {
    const router = stubRouter()
    const chainCtx = ref({
      run: { id: 'run-1', project_statuses: {}, resolved_order: ['p1', 'p2', 'p3'] },
      runId: 'run-1',
      tabs: [
        { projectId: 'p1', name: 'P1', isCompleted: true, status: 'completed' },
        { projectId: 'p2', name: 'P2', isCompleted: true, status: 'completed' },
        { projectId: 'p3', name: 'P3', isCompleted: true, status: 'completed' },
      ],
      locked: true,
    })
    const { useSequenceRunStore } = await import('@/stores/sequenceRunStore')
    const seqStore = useSequenceRunStore()
    seqStore.markReviewed('run-1', 'p2')

    const { showChainReview, chainReviewTab, handleChainReviewComplete } = useChainTabControls({
      chainCtx,
      projectId: ref('p1'),
      router,
      route: { query: { run: 'run-1' } },
    })
    chainReviewTab.value = { projectId: 'p1', name: 'P1', isCompleted: true }
    showChainReview.value = true

    await handleChainReviewComplete()

    expect(router.push).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'p3' },
      query: { run: 'run-1' },
    })
  })
})
