/**
 * useChainElectionLifecycle.spec.js — FE-6170
 *
 * Regression tests for the chain election lifecycle fixes:
 *   (a) release/unstage clears the transient selection + unlocks boxes
 *   (b) untick removes a participant in Electing state (toggle-off is reversible)
 *   (c) count < 2 disables the "Run sequential" launch button
 *   (d) emptied election returns the bulk-bar (jobs pane entry-point) to the no-jobs state
 *
 * Edition scope: CE.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

// ---------------------------------------------------------------------------
// Top-level hoisted mocks (required by Vitest module mocking — cannot be nested)
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Import subjects AFTER mocks are declared
// ---------------------------------------------------------------------------
import { useChainLifecycle } from '@/composables/useChainLifecycle'
import { useSequenceRunner } from '@/composables/useSequenceRunner'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import SequenceBulkBar from '@/components/sequence/SequenceBulkBar.vue'

// FE-9503a: the FE-6170 (a) releaseChain/onDissolved describe block was removed
// here -- releaseChain itself was deleted as zero-caller dead code (dossier in
// the FE-9503a project record). mockApiRelease stays wired (used below to
// assert unstageChain does NOT call release).

// FE-6171b REDEFINITION: unstageChain is now UNLOCK (locked=false), NOT dissolve.
// The old FE-6170 tests expected release(cancel)+onDissolved — those semantics are gone.
// New semantics verified in useChainLifecycle.fe6171b.spec.js.
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

// ---------------------------------------------------------------------------
// (b): untick removes a participant in Electing state
// ---------------------------------------------------------------------------
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

    // Untick = toggle off = removed from election
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

    // Roadmap rows have both id (rm PK) and project_id — toggle must key by project_id
    runner.toggle({ id: 'rm-item-pk', project_id: 'proj-RM', name: 'RM Item' })
    expect(runner.selectedIds.value).toContain('proj-RM')
    expect(runner.selectedIds.value).not.toContain('rm-item-pk')

    // Untick the same roadmap row by the same key (project_id)
    runner.toggle({ id: 'rm-item-pk', project_id: 'proj-RM', name: 'RM Item' })
    expect(runner.selectedIds.value).not.toContain('proj-RM')
  })
})

// ---------------------------------------------------------------------------
// (c): count < 2 disables the "Run sequential" launch button (SequenceBulkBar)
// ---------------------------------------------------------------------------
describe('FE-6170 (c): count < 2 disables the Run Sequential button', () => {
  it('disables the run button when count=1 (under the 2-project minimum)', () => {
    const wrapper = mount(SequenceBulkBar, { props: { count: 1 } })
    // The bar renders (count > 0)
    expect(wrapper.find('[data-testid="seq-bulk-bar"]').exists()).toBe(true)
    // Under-min hint shown
    expect(wrapper.find('[data-testid="seq-bulk-hint"]').exists()).toBe(true)
    // Run button is disabled
    const btn = wrapper.find('[data-testid="seq-run-btn"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('enables the run button when count=2 (meets the minimum)', () => {
    const wrapper = mount(SequenceBulkBar, { props: { count: 2 } })
    expect(wrapper.find('[data-testid="seq-bulk-hint"]').exists()).toBe(false)
    const btn = wrapper.find('[data-testid="seq-run-btn"]')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('electionActive stays false with 1 elected (keeps single-project play usable)', () => {
    // FE-6170: threshold raised from >0 to >=2
    const runner = useSequenceRunner()
    runner.toggle({ id: 'proj-A', name: 'Alpha' })
    // 1 project elected — electionActive is false so per-row play stays enabled
    expect(runner.electionActive.value).toBe(false)
    runner.toggle({ id: 'proj-B', name: 'Beta' })
    // 2 projects elected — electionActive is true, per-row play is faded
    expect(runner.electionActive.value).toBe(true)
  })

  it('SequenceBulkBar bar hidden when count=0 (no election)', () => {
    const wrapper = mount(SequenceBulkBar, { props: { count: 0 } })
    expect(wrapper.find('[data-testid="seq-bulk-bar"]').exists()).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// (d): emptied election returns the bulk-bar to no-jobs state
// ---------------------------------------------------------------------------
describe('FE-6170 (d): emptied election hides the bulk-bar (no-jobs state)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiRoadmapGet.mockResolvedValue({ data: { items: [] } })
  })

  it('bulk bar is hidden when selection is cleared', () => {
    const wrapper = mount(SequenceBulkBar, { props: { count: 0 } })
    expect(wrapper.find('[data-testid="seq-bulk-bar"]').exists()).toBe(false)
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

    // Seed with an active run
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

    // After hydrate with empty response (run dissolved), activeChainProjectIds empties
    mockApiList.mockResolvedValueOnce({ data: [] })
    await store.hydrate()

    expect(store.activeChainProjectIds).toHaveLength(0)
    expect(store.isProjectInActiveChain('proj-1')).toBe(false)
  })
})
