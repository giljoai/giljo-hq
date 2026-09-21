/**
 * ProjectTabs.fe6174b.spec.js — FE-6174b
 *
 * The conditional multi-project (chain) variant of the /jobs ProjectTabs shell.
 * Asserts:
 *   - DELETION TEST: chainCtx == null renders the solo controls only (no chain
 *     chrome) — the byte-identical solo path.
 *   - chainCtx present renders the N/M bar, tab strip, Stage Chain / Implement,
 *     and hides the project-id line.
 *   - Stage Chain / Implement reuse the chain lifecycle + implementation verbs.
 *   - Tab select navigates carrying ?run; Review opens the closeout modal.
 *
 * Mirrors the mock/mount scaffold of ProjectTabs.spec.js.
 * Edition scope: CE.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import ProjectTabs from '@/components/projects/ProjectTabs.vue'

const mockRoute = { query: { run: 'run-1' }, hash: '' }
const mockRouter = { push: vi.fn(), replace: vi.fn() }

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => mockRouter,
}))

const mockSortedJobs = { value: [] }
vi.mock('@/composables/useAgentJobs', () => ({
  useAgentJobs: () => ({ store: {}, sortedJobs: mockSortedJobs, loadJobs: vi.fn().mockResolvedValue([]) }),
}))
vi.mock('@/composables/useIntegrationStatus', () => ({
  useIntegrationStatus: () => ({ gitEnabled: { value: false }, serenaEnabled: { value: false } }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }) }))
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    subscribeToProject: vi.fn(), unsubscribe: vi.fn(),
    onConnectionChange: vi.fn().mockReturnValue(vi.fn()), on: vi.fn().mockReturnValue(vi.fn()),
  }),
}))
vi.mock('@/stores/notifications', () => ({ useNotificationStore: () => ({ clearForProject: vi.fn() }) }))

// Chain verbs — mocked so we can assert they are reused, not reimplemented.
const stageChainMock = vi.fn().mockResolvedValue({})
const unstageChainMock = vi.fn().mockResolvedValue({})
const launchChainHeadMock = vi.fn().mockResolvedValue(true)
const patchRunMock = vi.fn().mockResolvedValue({})
vi.mock('@/composables/useChainLifecycle', () => ({
  useChainLifecycle: () => ({ stageChain: stageChainMock, unstageChain: unstageChainMock }),
}))
vi.mock('@/composables/useChainImplementation', () => ({
  useChainImplementation: () => ({ launchChainHead: launchChainHeadMock }),
}))
// FE-9632: the chain screen now asks the store whether the run is underway. Default
// false -- every pre-existing case in this file describes a chain that has NOT
// started, and they must keep passing untouched (the pre-run screen is unchanged).
let mockRunIsRunning = false
vi.mock('@/stores/sequenceRunStore', () => ({
  useSequenceRunStore: () => ({ patchRun: patchRunMock, isRunning: () => mockRunIsRunning }),
}))

vi.mock('@/services/api', () => {
  const apiMock = {
    projects: {
      get: vi.fn().mockResolvedValue({
        data: {
          id: 'project-123', project_id: 'project-123', name: 'Test Project',
          description: 'd', status: 'active', staging_status: null,
          implementation_launched_at: null, execution_mode: 'multi_terminal',
          mission: '', product_id: 'prod-1', agents: [],
        },
      }),
      update: vi.fn().mockResolvedValue({}),
    },
    prompts: { staging: vi.fn().mockResolvedValue({ data: { prompt: 'p' } }) },
    orchestrator: { launchProject: vi.fn().mockResolvedValue({}) },
    products: { getMemoryEntries: vi.fn().mockResolvedValue({ data: { entries: [] } }) },
  }
  return { api: apiMock, default: apiMock }
})

function makeChainCtx(overrides = {}) {
  return {
    run: { id: 'run-1', execution_mode: 'multi_terminal', project_statuses: {}, locked: false },
    runId: 'run-1',
    tabs: [
      { projectId: 'project-123', order: 0, name: 'Project A', taxonomyAlias: 'FE-1', taxonomy: null, productId: 'prod-1', status: 'running', isCurrent: true, isCompleted: false, needsReview: false, isStarted: true },
      { projectId: 'p2', order: 1, name: 'Project B', taxonomyAlias: 'FE-2', taxonomy: null, productId: 'prod-1', status: 'awaiting_review', isCurrent: false, isCompleted: false, needsReview: true, isStarted: true },
    ],
    counter: { n: 1, m: 2 },
    currentPid: 'project-123',
    headMission: 'Overarching mission text',
    conductor: { agentId: 'cond', projectId: 'p1', label: 'Conductor A' },
    locked: false,
    statusFor: () => '',
    ...overrides,
  }
}

let currentTestPinia = null
function createWrapper(extraProps = {}) {
  const vuetify = createVuetify()
  const project = {
    id: 'project-123', project_id: 'project-123', name: 'Test Project',
    description: 'd', status: 'active', execution_mode: 'multi_terminal',
  }
  return mount(ProjectTabs, {
    props: { project, orchestrator: null, ...extraProps },
    global: {
      plugins: [vuetify, currentTestPinia],
      stubs: {
        LaunchTab: { name: 'LaunchTab', template: '<div class="launch-tab-stub" />', props: ['project'] },
        JobsTab: { name: 'JobsTab', template: '<div class="jobs-tab-stub" />', props: ['project', 'chainCtx'] },
        CloseoutModal: { name: 'CloseoutModal', template: '<div class="closeout-modal-stub" />', props: ['show', 'projectId', 'projectName', 'productId'], emits: ['close', 'closeout', 'continue'] },
        ChainModeBar: { name: 'ChainModeBar', template: '<div class="chain-mode-bar-stub" />', props: ['counter', 'mode'] },
        ProjectTabStrip: { name: 'ProjectTabStrip', template: '<div class="tab-strip-stub" />', props: ['tabs', 'activePid'], emits: ['select'] },
        ChainMissionWindow: { name: 'ChainMissionWindow', template: '<div class="mission-window-stub" />', props: ['mission'] },
        'v-tooltip': { template: '<div><slot /><slot name="activator" /></div>' },
        'v-progress-circular': { template: '<div />' },
      },
    },
  })
}

describe('ProjectTabs FE-6174b — deletion test (solo, chainCtx null)', () => {
  beforeEach(() => {
    currentTestPinia = createPinia()
    setActivePinia(currentTestPinia)
    mockRoute.query = {}
    vi.clearAllMocks()
    mockSortedJobs.value = []
  })

  it('renders only the SOLO controls and no chain chrome when chainCtx is null', async () => {
    const wrapper = createWrapper({ chainCtx: null })
    await flushPromises()
    expect(wrapper.find('[data-testid="stage-project-btn"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="launch-jobs-btn"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="stage-chain-btn"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="implement-chain-btn"]').exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'ChainModeBar' }).exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'ProjectTabStrip' }).exists()).toBe(false)
    // Solo keeps the project-id line.
    expect(wrapper.find('.project-id').exists()).toBe(true)
  })
})

describe('ProjectTabs FE-6174b — chain variant (chainCtx present)', () => {
  beforeEach(() => {
    currentTestPinia = createPinia()
    setActivePinia(currentTestPinia)
    mockRoute.query = { run: 'run-1' }
    vi.clearAllMocks()
    mockSortedJobs.value = []
  })

  it('renders the N/M bar, tab strip, mission window, and chain buttons; hides project-id', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx() })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ChainModeBar' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ProjectTabStrip' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ChainMissionWindow' }).exists()).toBe(true)
    expect(wrapper.find('[data-testid="stage-chain-btn"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="implement-chain-btn"]').exists()).toBe(true)
    // Solo controls + project-id line are gone in chain mode.
    expect(wrapper.find('[data-testid="stage-project-btn"]').exists()).toBe(false)
    expect(wrapper.find('.project-id').exists()).toBe(false)
  })

  it('Stage Chain reuses stageChain(run)', async () => {
    const ctx = makeChainCtx()
    const wrapper = createWrapper({ chainCtx: ctx })
    await flushPromises()
    await wrapper.find('[data-testid="stage-chain-btn"]').trigger('click')
    await flushPromises()
    expect(stageChainMock).toHaveBeenCalledWith(ctx.run)
  })

  // FE-6173 C1: Implement is ready only when the run is pending + locked + has a
  // chain mission + all members staging_complete (not merely locked).
  const READY_RUN = {
    id: 'run-1',
    execution_mode: 'multi_terminal',
    locked: true,
    status: 'pending',
    chain_mission: 'Overarching chain mission',
    project_ids: ['project-123', 'p2'],
    project_statuses: { 'project-123': 'staging_complete', p2: 'staging_complete' },
  }

  it('shows Unstage Chain + Implement enabled when the chain is staged and ready', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ locked: true, run: { ...READY_RUN } }) })
    await flushPromises()
    expect(wrapper.find('[data-testid="stage-chain-btn"]').text()).toContain('Unstage Chain')
    expect(wrapper.find('[data-testid="implement-chain-btn"]').attributes('disabled')).toBeUndefined()
  })

  it('Implement is disabled until the chain is staged (locked)', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ locked: false }) })
    await flushPromises()
    expect(wrapper.find('[data-testid="implement-chain-btn"]').attributes('disabled')).toBeDefined()
  })

  it('Implement reuses launchChainHead(headProjectId)', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ locked: true, run: { ...READY_RUN } }) })
    await flushPromises()
    await wrapper.find('[data-testid="implement-chain-btn"]').trigger('click')
    await flushPromises()
    // FE-9629: Implement opens the HEAD member's gate (run.project_ids[0] ->
    // 'project-123') and navigates there; it no longer copies a conductor prompt.
    expect(launchChainHeadMock).toHaveBeenCalledWith('project-123')
  })

  it('tab select navigates to that project carrying ?run', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx() })
    await flushPromises()
    wrapper.findComponent({ name: 'ProjectTabStrip' }).vm.$emit('select', 'p2')
    await flushPromises()
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'ProjectLaunch', params: { projectId: 'p2' }, query: { run: 'run-1' } }),
    )
  })

  it('Review project button opens the chain closeout modal for the viewed needsReview project', async () => {
    // Make the viewed project (project-123) a needsReview member
    const ctxWithNeedsReview = makeChainCtx({
      tabs: [
        { projectId: 'project-123', order: 0, name: 'Project A', taxonomyAlias: 'FE-1', taxonomy: null, productId: 'prod-1', status: 'completed', isCurrent: true, isCompleted: true, needsReview: true, isStarted: true },
        { projectId: 'p2', order: 1, name: 'Project B', taxonomyAlias: 'FE-2', taxonomy: null, productId: 'prod-1', status: 'awaiting_review', isCurrent: false, isCompleted: false, needsReview: false, isStarted: true },
      ],
    })
    const wrapper = createWrapper({ chainCtx: ctxWithNeedsReview })
    await flushPromises()

    // Switch to jobs tab so the banner is visible
    await wrapper.find('[data-testid="jobs-tab"]').trigger('click')
    await flushPromises()

    // Click the "Review project" button (data-testid=close-project-btn)
    await wrapper.find('[data-testid="close-project-btn"]').trigger('click')
    await flushPromises()

    // The chain CloseoutModal (suppress-navigation, projectId=project-123) must open
    const modals = wrapper.findAllComponents({ name: 'CloseoutModal' })
    const chainModal = modals.find((m) => m.props('show') === true && m.props('projectId') === 'project-123')
    expect(chainModal).toBeTruthy()

    // The solo CloseoutModal (no suppress-navigation) must remain closed
    const soloModal = modals.find((m) => {
      const showProp = m.props('show')
      const hasSuppressNav = m.props('suppressNavigation') === true || m.attributes('suppress-navigation') !== undefined
      return showProp === true && !hasSuppressNav
    })
    expect(soloModal).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// FE-9632 — the RUNNING chain screen. Mounted, because the point of the change is
// what is on screen: the staging affordances have to be GONE (v-if), not merely
// disabled, and Stop chain has to be present on BOTH tabs.
// ---------------------------------------------------------------------------

describe('ProjectTabs FE-9632 — running chain', () => {
  const RUNNING_RUN = {
    id: 'run-1',
    execution_mode: 'subagent',
    locked: true,
    status: 'running',
    chain_mission: 'Overarching chain mission',
    project_ids: ['project-123', 'p2'],
    resolved_order: ['project-123', 'p2'],
    project_statuses: { 'project-123': 'implementing', p2: 'pending' },
  }

  beforeEach(() => {
    currentTestPinia = createPinia()
    setActivePinia(currentTestPinia)
    mockRoute.query = { run: 'run-1' }
    vi.clearAllMocks()
    mockSortedJobs.value = []
    mockRunIsRunning = true
  })

  afterEach(() => {
    mockRunIsRunning = false
  })

  it('shows Stop chain on the Staging tab', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ run: RUNNING_RUN, locked: true }) })
    await flushPromises()
    expect(wrapper.find('[data-testid="stop-chain-btn"]').exists()).toBe(true)
  })

  it('shows Stop chain on the Implementation tab too', async () => {
    mockRoute.query = { run: 'run-1', tab: 'jobs' }
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ run: RUNNING_RUN, locked: true }) })
    await flushPromises()
    expect(wrapper.find('[data-testid="jobs-tab"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="stop-chain-btn"]').exists()).toBe(true)
  })

  it('REMOVES Stage/Unstage Chain rather than disabling it', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ run: RUNNING_RUN, locked: true }) })
    await flushPromises()
    expect(wrapper.find('[data-testid="stage-chain-btn"]').exists()).toBe(false)
  })

  it('REMOVES Implement rather than disabling it', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ run: RUNNING_RUN, locked: true }) })
    await flushPromises()
    expect(wrapper.find('[data-testid="implement-chain-btn"]').exists()).toBe(false)
  })

  it('does not fall back to the SOLO staging buttons when the chain ones are hidden', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ run: RUNNING_RUN, locked: true }) })
    await flushPromises()
    expect(wrapper.find('[data-testid="stage-project-btn"]').exists()).toBe(false)
  })

  it('replaces the Execution Mode selector with the read-only readout', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ run: RUNNING_RUN, locked: true }) })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ExecutionModeSelector' }).exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'ChainModeBar' }).props('mode')).toBe('subagent')
  })

  it('keeps the read-only mode readout on the Implementation tab (the bar renders on both)', async () => {
    mockRoute.query = { run: 'run-1', tab: 'jobs' }
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ run: RUNNING_RUN, locked: true }) })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ChainModeBar' }).props('mode')).toBe('subagent')
  })

  it('passes no mode when the run carries no execution_mode (old runs render nothing)', async () => {
    const wrapper = createWrapper({
      chainCtx: makeChainCtx({ run: { ...RUNNING_RUN, execution_mode: null }, locked: true }),
    })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ChainModeBar' }).props('mode')).toBe('')
  })

  it('passes no mode before the run starts, so the pre-run bar is unchanged', async () => {
    mockRunIsRunning = false
    const wrapper = createWrapper({ chainCtx: makeChainCtx() })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ChainModeBar' }).props('mode')).toBe('')
  })

  it('keeps the chain chrome (counter + tab strip) while running', async () => {
    const wrapper = createWrapper({ chainCtx: makeChainCtx({ run: RUNNING_RUN, locked: true }) })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ChainModeBar' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ProjectTabStrip' }).exists()).toBe(true)
  })

  it('shows no Stop chain in SOLO mode even if the flag were somehow set', async () => {
    const wrapper = createWrapper({ chainCtx: null })
    await flushPromises()
    expect(wrapper.find('[data-testid="stop-chain-btn"]').exists()).toBe(false)
  })
})
