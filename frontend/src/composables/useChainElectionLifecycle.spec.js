import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const {
  mockShowToast,
  mockCopyFn,
  mockApiRelease,
  mockApiList,
  mockApiCreate,
  mockApiRoadmapGet,
  mockRouterPush,
} = vi.hoisted(() => ({
  mockShowToast: vi.fn(),
  mockCopyFn: vi.fn(() => Promise.resolve(true)),
  mockApiRelease: vi.fn(),
  mockApiList: vi.fn(),
  mockApiCreate: vi.fn(),
  mockApiRoadmapGet: vi.fn(),
  mockRouterPush: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: mockCopyFn }),
}))

const { mockApiUpdate } = vi.hoisted(() => ({
  mockApiUpdate: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const apiObj = {
    sequenceRuns: {
      create: mockApiCreate,
      get: vi.fn(),
      update: mockApiUpdate,
      release: mockApiRelease,
      list: mockApiList,
      removeMember: vi.fn(),
    },
    roadmap: { get: mockApiRoadmapGet },
    prompts: { termination: vi.fn() },
    messages: { sendUnified: vi.fn() },
    agentJobs: { simpleHandover: vi.fn() },
    projects: { restage: vi.fn(), launchImplementation: vi.fn() },
  }
  return { api: apiObj, default: apiObj }
})

vi.mock('vue-router', () => ({ useRouter: () => ({ push: mockRouterPush }) }))

import { useChainLifecycle } from '@/composables/useChainLifecycle'
import { useSequenceRunner } from '@/composables/useSequenceRunner'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'


describe('FE-6171b (redef): unstageChain = UNLOCK, not dissolve', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiRoadmapGet.mockResolvedValue({ data: { items: [] } })
  })

  it('PATCHes locked=false and does NOT call release (chain kept intact)', async () => {
    mockApiUpdate.mockResolvedValueOnce({
      data: {
        id: 'run-2',
        status: 'pending',
        locked: false,
        project_ids: [],
        resolved_order: [],
        project_statuses: {},
        execution_mode: 'multi_terminal',
        current_index: 0,
      },
    })

    const { unstageChain } = useChainLifecycle()
    const updated = await unstageChain({ id: 'run-2', status: 'pending', locked: true })

    expect(mockApiRelease).not.toHaveBeenCalled()
    expect(mockApiUpdate).toHaveBeenCalledWith('run-2', { locked: false })
    expect(updated).not.toBeNull()
    expect(updated.locked).toBe(false)
  })

  it('returns null when PATCH fails', async () => {
    mockApiUpdate.mockRejectedValueOnce(new Error('network fail'))

    const { unstageChain } = useChainLifecycle()
    const updated = await unstageChain({ id: 'run-2', status: 'pending', locked: true })

    expect(updated).toBeNull()
    expect(mockApiRelease).not.toHaveBeenCalled()
  })
})

describe('FE-6170 (b): untick removes a participant (toggle-off in Electing state)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiRoadmapGet.mockResolvedValue({ data: { items: [] } })
  })

  it('toggle twice removes the project from selection', () => {
    const runner = useSequenceRunner()

    runner.toggle({ id: 'proj-A', name: 'Alpha' })
    expect(runner.selectedIds.value).toContain('proj-A')
    expect(runner.selectedCount.value).toBe(1)

    runner.toggle({ id: 'proj-A', name: 'Alpha' })
    expect(runner.selectedIds.value).not.toContain('proj-A')
    expect(runner.selectedCount.value).toBe(0)
  })

  it('untick of one project in a 2-project election removes only that project', () => {
    const runner = useSequenceRunner()

    runner.toggle({ id: 'proj-A', name: 'Alpha' })
    runner.toggle({ id: 'proj-B', name: 'Beta' })
    expect(runner.selectedCount.value).toBe(2)

    runner.toggle({ id: 'proj-A', name: 'Alpha' })
    expect(runner.selectedIds.value).toEqual(['proj-B'])
    expect(runner.selectedCount.value).toBe(1)
  })

  it('toggle on roadmap row (project_id key) works correctly', () => {
    const runner = useSequenceRunner()

    runner.toggle({ id: 'rm-item-pk', project_id: 'proj-RM', name: 'RM Item' })
    expect(runner.selectedIds.value).toContain('proj-RM')
    expect(runner.selectedIds.value).not.toContain('rm-item-pk')

    runner.toggle({ id: 'rm-item-pk', project_id: 'proj-RM', name: 'RM Item' })
    expect(runner.selectedIds.value).not.toContain('proj-RM')
  })
})

describe('FE-6170 (c): the 2-project election threshold', () => {
  it('electionActive stays false with 1 elected (keeps single-project play usable)', () => {
    const runner = useSequenceRunner()
    runner.toggle({ id: 'proj-A', name: 'Alpha' })
    expect(runner.electionActive.value).toBe(false)
    runner.toggle({ id: 'proj-B', name: 'Beta' })
    expect(runner.electionActive.value).toBe(true)
  })

})

describe('FE-6170 (d): emptied election hides the bulk-bar (no-jobs state)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiRoadmapGet.mockResolvedValue({ data: { items: [] } })
  })

  it('clear() empties selection so count drops to 0', () => {
    const runner = useSequenceRunner()

    runner.toggle({ id: 'proj-A', name: 'Alpha' })
    runner.toggle({ id: 'proj-B', name: 'Beta' })
    expect(runner.selectedCount.value).toBe(2)

    runner.clear()
    expect(runner.selectedCount.value).toBe(0)
    expect(runner.electionActive.value).toBe(false)
  })

  it('sequenceRunStore: dissolved run drops out so activeChainProjectIds empties', async () => {
    const store = useSequenceRunStore()

    store._testSeedRuns([
      {
        id: 'run-X',
        project_ids: ['proj-1', 'proj-2'],
        resolved_order: ['proj-1', 'proj-2'],
        current_index: 0,
        status: 'pending',
        execution_mode: 'multi_terminal',
        project_statuses: { 'proj-1': 'pending', 'proj-2': 'pending' },
      },
    ])
    expect(store.activeChainProjectIds).toEqual(['proj-1', 'proj-2'])
    expect(store.isProjectInActiveChain('proj-1')).toBe(true)

    mockApiList.mockResolvedValueOnce({ data: [] })
    await store.hydrate()

    expect(store.activeChainProjectIds).toHaveLength(0)
    expect(store.isProjectInActiveChain('proj-1')).toBe(false)
  })
})
