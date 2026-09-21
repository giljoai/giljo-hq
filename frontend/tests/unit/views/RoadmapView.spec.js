/**
 * RoadmapView.vue — FE-6022b
 *
 * Covers the load-bearing view behavior:
 *   - reorder recomputes sort_order = position and PATCHes the WHOLE list with
 *     the correct [{id, sort_order}] payload (this is what makes "survives
 *     refresh" true — GET re-sorts by these priorities).
 *   - demote moves an item to the bottom and persists the same way.
 *   - a 404 from GET /roadmap (no active product) shows the info alert.
 *
 * Edition Scope: CE
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

// ── hoisted spies ────────────────────────────────────────────────────────────
const { mockGet, mockReorder, mockRemoveItem, wsHandlers, mockWsOn, resyncCallbacks, mockRegisterResync } = vi.hoisted(() => {
  const handlers = {}
  const resyncs = []
  return {
    mockGet: vi.fn(),
    mockReorder: vi.fn().mockResolvedValue({ data: {} }),
    mockRemoveItem: vi.fn().mockResolvedValue({ data: { removed: 1 } }),
    wsHandlers: handlers,
    mockWsOn: vi.fn((type, cb) => {
      handlers[type] = cb
      return () => {
        delete handlers[type]
      }
    }),
    // FE-9407: capture the reconnect-resync callback so a WS reconnect can be
    // driven directly. The real router only fires it from its own connection
    // listener, which this spec does not stand up.
    resyncCallbacks: resyncs,
    mockRegisterResync: vi.fn((cb) => {
      resyncs.push(cb)
      return () => {
        const i = resyncs.indexOf(cb)
        if (i !== -1) resyncs.splice(i, 1)
      }
    }),
  }
})

const ITEMS = [
  { id: 'a', item_type: 'project', project_id: 'pa', task_id: null, title: 'A', taxonomy_alias: 'BE-0001', sort_order: 0, risk: 'low', complexity: 'heavy' },
  { id: 'b', item_type: 'task', project_id: null, task_id: 'tb', title: 'B', taxonomy_alias: 'TASK-1', sort_order: 1, risk: 'high', complexity: 'light' },
  { id: 'c', item_type: 'project', project_id: 'pc', task_id: null, title: 'C', taxonomy_alias: 'BE-0002', sort_order: 2, risk: 'med', complexity: 'med' },
]

// ── mocks ────────────────────────────────────────────────────────────────────
vi.mock('@/services/api', () => {
  const svc = {
    roadmap: { get: mockGet, reorder: mockReorder, removeItem: mockRemoveItem },
    taxonomyTypes: { list: vi.fn().mockResolvedValue({ data: [] }) },
    tasks: {
      get: vi.fn().mockResolvedValue({ data: {} }),
      convertToProject: vi.fn().mockResolvedValue({ data: { name: 'New Project' } }),
    },
  }
  return { default: svc, api: svc }
})

// FE-9564: mutable so a test can drop the viewed product and prove the
// copy-prompt degrades to the name-only wording instead of emitting
// product_id="undefined".
const { productState } = vi.hoisted(() => ({
  productState: { current: { id: 'prod-1', name: 'Test Product' } },
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    // FE-9502c: RoadmapView's product label/indicator now reads currentProduct
    // (the viewed tab), not the server's single activeProduct.
    get currentProduct() {
      return productState.current
    },
    activeProduct: { id: 'prod-1', name: 'Test Product' },
    effectiveProductId: 'prod-1',
    fetchActiveProduct: vi.fn().mockResolvedValue(),
  }),
}))

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    projects: [],
    fetchProject: vi.fn().mockResolvedValue(null),
    activateProject: vi.fn().mockResolvedValue(),
    deactivateProject: vi.fn().mockResolvedValue(),
  }),
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({ on: mockWsOn }),
}))

// RoadmapView imports only registerReconnectResync from this module.
vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: mockRegisterResync,
}))

// FE-9553: was `showToast: vi.fn()`, a FRESH spy per useToast() call -- so the
// spy the view called was never the spy a test could see, and no assertion
// about a toast in this file could pass or fail for the right reason. Shared
// hoisted spy, matching the pattern in useHubNotifications.spec.js.
const showToastSpy = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastSpy }),
}))

vi.mock('@/composables/useTaskCrud', () => ({
  useTaskCrud: () => ({
    showTaskDialog: ref(false),
    editingTask: ref(null),
    saving: ref(false),
    currentTask: ref({}),
    editTask: vi.fn(),
    cancelTask: vi.fn(),
    saveTask: vi.fn().mockResolvedValue(),
  }),
}))

// Stub vuedraggable so the suite drives the move via an `update:modelValue`
// emit instead of pulling SortableJS into jsdom. It renders the #item slot per
// element exactly like the real component.
vi.mock('vuedraggable', () => ({
  default: {
    name: 'draggable',
    props: { modelValue: { type: Array, default: () => [] } },
    emits: ['update:modelValue'],
    template:
      '<div class="vdraggable"><div v-for="(element, index) in modelValue" :key="element.id"><slot name="item" :element="element" :index="index" /></div></div>',
  },
}))

import RoadmapView from '@/views/RoadmapView.vue'

const stubs = {
  RoadmapCard: true,
  RoadmapPromptActions: true,
  ProjectCreateEditDialog: true,
  TaskEditDialog: true,
  BaseDialog: true,
  'v-container': { template: '<div><slot /></div>' },
  'v-row': { template: '<div><slot /></div>' },
  'v-col': { template: '<div><slot /></div>' },
  'v-alert': { template: '<div class="v-alert"><slot /></div>' },
  'v-switch': { template: '<input type="checkbox" />' },
  'v-btn': { template: '<button class="v-btn"><slot /></button>' },
  'v-icon': { template: '<i><slot /></i>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /></div>' },
  'v-progress-circular': { template: '<div />' },
}

async function mountView() {
  const w = mount(RoadmapView, { global: { stubs } })
  await flushPromises()
  return w
}

// TSK-6243: the shared tests/setup.js installs a no-op localStorage stub whose
// getItem is a bare vi.fn() (returns undefined, never null) and whose setItem/
// removeItem/clear don't persist anything. A real browser (and real jsdom)
// localStorage returns null for a missing key and actually stores. The
// reload-continuity assertions below (getItem toBeNull, and a spinner re-raised
// from a persisted stamp) need that real behavior, so install a correct,
// Map-backed localStorage LOCAL to this spec. A fresh store per test keeps cases
// isolated; scoping it here (not in the shared setup) means no other spec that
// relies on the shared stub is affected.
beforeEach(() => {
  const store = new Map()
  window.localStorage = {
    getItem: (k) => (store.has(String(k)) ? store.get(String(k)) : null),
    setItem: (k, v) => store.set(String(k), String(v)),
    removeItem: (k) => store.delete(String(k)),
    clear: () => store.clear(),
    key: (i) => Array.from(store.keys())[i] ?? null,
    get length() {
      return store.size
    },
  }
})

// Clear the stamp between every test so a persisted spinner never leaks across
// cases (the per-test beforeEach above already gives a fresh store; this stays
// as a belt-and-suspenders guard).
afterEach(() => {
  localStorage.clear()
  // FE-9564: restore the viewed product so no test inherits another's
  // override -- each test owns its own setup.
  productState.current = { id: 'prod-1', name: 'Test Product' }
})

describe('RoadmapView.vue — reorder persistence', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: { summary: null }, items: ITEMS.map((i) => ({ ...i })) } })
  })

  it('loads the sort_order-sorted items from GET /roadmap', async () => {
    const w = await mountView()
    expect(mockGet).toHaveBeenCalled()
    expect(w.vm.items.map((i) => i.id)).toEqual(['a', 'b', 'c'])
  })

  it('a vuedraggable move PATCHes the whole list with recomputed sort_order = position', async () => {
    const w = await mountView()
    const byId = Object.fromEntries(w.vm.items.map((i) => [i.id, i]))
    const drag = w.findComponent({ name: 'draggable' })
    // user drags 'c' above 'a' -> vuedraggable emits the new visible order
    drag.vm.$emit('update:modelValue', [byId.c, byId.a, byId.b])
    await flushPromises()
    expect(mockReorder).toHaveBeenCalledTimes(1)
    expect(mockReorder).toHaveBeenCalledWith([
      { id: 'c', sort_order: 0 },
      { id: 'a', sort_order: 1 },
      { id: 'b', sort_order: 2 },
    ], 'prod-1')
    // optimistic local order updated
    expect(w.vm.items.map((i) => i.id)).toEqual(['c', 'a', 'b'])
  })

  it('persists exactly the order vuedraggable produces (move down)', async () => {
    const w = await mountView()
    const byId = Object.fromEntries(w.vm.items.map((i) => [i.id, i]))
    const drag = w.findComponent({ name: 'draggable' })
    // user drags 'a' below 'b' -> [b, a, c]
    drag.vm.$emit('update:modelValue', [byId.b, byId.a, byId.c])
    await flushPromises()
    expect(mockReorder).toHaveBeenCalledWith([
      { id: 'b', sort_order: 0 },
      { id: 'a', sort_order: 1 },
      { id: 'c', sort_order: 2 },
    ], 'prod-1')
  })

  it('demote moves an item to the bottom and persists', async () => {
    const w = await mountView()
    await w.vm.demote({ id: 'a' })
    expect(mockReorder).toHaveBeenCalledWith([
      { id: 'b', sort_order: 0 },
      { id: 'c', sort_order: 1 },
      { id: 'a', sort_order: 2 },
    ], 'prod-1')
    expect(w.vm.items.map((i) => i.id)).toEqual(['b', 'c', 'a'])
  })

  it('rolls the optimistic order back if the PATCH fails', async () => {
    const w = await mountView()
    const byId = Object.fromEntries(w.vm.items.map((i) => [i.id, i]))
    mockReorder.mockRejectedValueOnce(new Error('boom'))
    // re-fetch after rollback returns the original order
    mockGet.mockResolvedValueOnce({ data: { product_id: 'prod-1', roadmap: null, items: ITEMS.map((i) => ({ ...i })) } })
    const drag = w.findComponent({ name: 'draggable' })
    drag.vm.$emit('update:modelValue', [byId.c, byId.a, byId.b])
    await flushPromises()
    expect(w.vm.items.map((i) => i.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('RoadmapView.vue — remove from roadmap (FE-6022c-polish)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: ITEMS.map((i) => ({ ...i })) } })
    mockRemoveItem.mockResolvedValue({ data: { removed: 1 } })
  })

  it('optimistically removes the card and calls DELETE with the item id', async () => {
    const w = await mountView()
    await w.vm.removeItem({ id: 'b' })
    await flushPromises()
    expect(mockRemoveItem).toHaveBeenCalledWith('b', 'prod-1')
    expect(w.vm.items.map((i) => i.id)).toEqual(['a', 'c']) // 'b' gone
  })

  it('rolls the removal back if the DELETE fails', async () => {
    const w = await mountView()
    mockRemoveItem.mockRejectedValueOnce(new Error('boom'))
    await w.vm.removeItem({ id: 'b' })
    await flushPromises()
    expect(w.vm.items.map((i) => i.id)).toEqual(['a', 'b', 'c']) // restored
  })
})

// ── 0006 hard auto-drop is server-side ───────────────────────────────────────
// Terminal projects/tasks are excluded by the backend get_roadmap read, NOT by
// the FE. These pin that contract: the view renders exactly what GET returns
// (it must NOT re-implement a client-side terminal filter that could diverge
// from / mask the server), and the existing per-card remove control still works
// for a live item the user no longer wants planned.
describe('RoadmapView.vue — 0006 auto-drop is server-side', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders exactly the items GET returns (server already excluded terminal items)', async () => {
    // Server returns only the live items — a completed project was dropped server-side.
    const live = [
      { ...ITEMS[0], status: 'inactive' },
      { ...ITEMS[1], status: 'pending' },
    ]
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: live } })
    const w = await mountView()
    expect(w.vm.items.map((i) => i.id)).toEqual(['a', 'b'])
    expect(w.vm.displayItems.map((i) => i.id)).toEqual(['a', 'b'])
  })

  it('applies NO client-side terminal filter (a terminal item from the server still renders)', async () => {
    // If the server (hypothetically) returns a terminal item, the FE renders it
    // verbatim — proving the drop is purely server-side and the view never
    // double-filters or masks the read contract.
    const withTerminal = [
      { ...ITEMS[0], status: 'completed' },
      { ...ITEMS[1], status: 'pending' },
    ]
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: withTerminal } })
    const w = await mountView()
    expect(w.vm.items.map((i) => i.id)).toEqual(['a', 'b'])
  })

  it('the per-card remove control evicts a still-live item via DELETE', async () => {
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: ITEMS.map((i) => ({ ...i })) } })
    mockRemoveItem.mockResolvedValue({ data: { removed: 1 } })
    const w = await mountView()
    await w.vm.removeItem({ id: 'a' })
    await flushPromises()
    expect(mockRemoveItem).toHaveBeenCalledWith('a', 'prod-1')
    expect(w.vm.items.map((i) => i.id)).toEqual(['b', 'c'])
  })
})

describe('RoadmapView.vue — fold toggle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: ITEMS.map((i) => ({ ...i })) } })
  })

  it('fold toggle off hides task items from the displayed list (reorder still over full set)', async () => {
    const w = await mountView()
    expect(w.vm.displayItems.map((i) => i.id)).toEqual(['a', 'b', 'c'])
    w.vm.foldInTasks = false
    await flushPromises()
    expect(w.vm.displayItems.map((i) => i.id)).toEqual(['a', 'c']) // task 'b' hidden
    // underlying source of truth is untouched
    expect(w.vm.items.map((i) => i.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('RoadmapView.vue — empty / no-product states', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the no-active-product alert when GET returns 404', async () => {
    mockGet.mockRejectedValue({ response: { status: 404 } })
    const w = await mountView()
    expect(w.text()).toContain('No product is open')
  })

  it('shows the empty-roadmap state when items is empty', async () => {
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: [] } })
    const w = await mountView()
    expect(w.text()).toContain('No roadmap yet')
  })
})

describe('RoadmapView.vue — copy-prompt bridge (FE-6022c)', () => {
  let mockWriteText
  beforeEach(() => {
    vi.clearAllMocks()
    mockWriteText = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: mockWriteText }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
  })

  it('shows "Create Roadmap" when empty and copies a build prompt w/ product + host (no longer sets the indicator)', async () => {
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: [] } })
    const w = await mountView()
    // FE-9617: the Create/Refresh label lives in the toolbar's split button now.
    expect(w.findComponent({ name: 'RoadmapPromptActions' }).props('isEmpty')).toBe(true)

    await w.vm.copyRoadmapPrompt()
    expect(mockWriteText).toHaveBeenCalledTimes(1)
    const prompt = mockWriteText.mock.calls[0][0]
    expect(prompt).toContain('Build a product roadmap')
    expect(prompt).toContain('Test Product') // active product NAME embedded
    expect(prompt).toContain('host:') // env/host embedded
    expect(prompt).toContain('save_roadmap')
    expect(prompt).toContain('get_roadmap') // FE-6240: create now reads first so it trips agent_active
    // FE-6240: copy no longer raises the spinner — the agent's roadmap:agent_active does.
    expect(w.vm.waiting).toBe(false)
  })

  it('shows "Refresh Roadmap" when items exist and copies a re-rank prompt (reads get_roadmap)', async () => {
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: ITEMS.map((i) => ({ ...i })) } })
    const w = await mountView()
    expect(w.findComponent({ name: 'RoadmapPromptActions' }).props('isEmpty')).toBe(false)

    await w.vm.copyRoadmapPrompt()
    const prompt = mockWriteText.mock.calls[0][0]
    expect(prompt).toContain('Re-rank the roadmap')
    expect(prompt).toContain('get_roadmap')
  })

  // FE-9564 regression. Both roadmap tools take an optional product_id and both
  // misbehave without it on a tenant owning more than one product: get_roadmap
  // silently resolves to whatever product is DEFAULT, and save_roadmap refuses
  // with PRODUCT_AMBIGUOUS. The page knows exactly which product it is showing,
  // so the prompt must say so -- otherwise the user pastes a five-step
  // instruction that fails on step five.
  it('scopes BOTH roadmap calls to the viewed product id, in create and re-rank modes', async () => {
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: [] } })
    const create = await mountView()
    await create.vm.copyRoadmapPrompt()
    const createPrompt = mockWriteText.mock.calls[0][0]
    expect(createPrompt).toContain('get_roadmap(product_id="prod-1")')
    expect(createPrompt).toContain('save_roadmap MCP tool with product_id="prod-1" and')

    mockWriteText.mockClear()
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: ITEMS.map((i) => ({ ...i })) } })
    const rerank = await mountView()
    await rerank.vm.copyRoadmapPrompt()
    const rerankPrompt = mockWriteText.mock.calls[0][0]
    expect(rerankPrompt).toContain('get_roadmap(product_id="prod-1")')
    expect(rerankPrompt).toContain('save_roadmap with product_id="prod-1" and')
  })

  it('falls back to the unscoped wording when no product is being viewed', async () => {
    productState.current = null
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: [] } })
    const w = await mountView()
    await w.vm.copyRoadmapPrompt()
    const prompt = mockWriteText.mock.calls[0][0]
    // No id to give, so no half-written argument -- and never the string
    // "undefined", which is what a naive interpolation would emit.
    expect(prompt).toContain('Call get_roadmap first')
    expect(prompt).toContain('save_roadmap MCP tool with')
    expect(prompt).not.toContain('product_id=')
    expect(prompt).not.toContain('undefined')
  })

  it('does NOT set the waiting indicator when the clipboard copy fails', async () => {
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: [] } })
    // No secure clipboard + execCommand returns falsy -> copy fails.
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    document.execCommand = vi.fn().mockReturnValue(false)
    const w = await mountView()
    await w.vm.copyRoadmapPrompt()
    expect(w.vm.waiting).toBe(false)
  })
})

describe('RoadmapView.vue — one-off editable prompt, re-homed to the toolbar menu (FE-9617)', () => {
  let mockWriteText
  beforeEach(() => {
    vi.clearAllMocks()
    mockWriteText = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: mockWriteText }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: ITEMS.map((i) => ({ ...i })) } })
  })

  it('no longer renders the page-level "Add my own instructions" checkbox', async () => {
    const w = await mountView()
    expect(w.text()).not.toContain('Add my own instructions')
  })

  it('hands the toolbar the generated prompt for the current mode', async () => {
    const w = await mountView()
    expect(w.vm.currentPromptText).toContain('Re-rank the roadmap') // non-empty roadmap -> refresh
    const actions = w.findComponent({ name: 'RoadmapPromptActions' })
    expect(actions.exists()).toBe(true)
    expect(actions.props('promptText')).toContain('Re-rank the roadmap')
    expect(actions.props('isEmpty')).toBe(false)
  })

  it('a copy with no edited text copies the generated prompt', async () => {
    const w = await mountView()
    w.findComponent({ name: 'RoadmapPromptActions' }).vm.$emit('copy', undefined)
    await flushPromises()
    expect(mockWriteText.mock.calls[0][0]).toContain('Re-rank the roadmap')
  })

  it('a copy carrying edited text copies that text through the SAME clipboard path', async () => {
    const w = await mountView()
    w.findComponent({ name: 'RoadmapPromptActions' }).vm.$emit('copy', 'work on the UI first, then the database')
    await flushPromises()
    expect(mockWriteText).toHaveBeenCalledWith('work on the UI first, then the database')
    expect(showToastSpy).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
  })

  it('a click event argument is not mistaken for edited prompt text', async () => {
    const w = await mountView()
    await w.vm.copyRoadmapPrompt(new MouseEvent('click'))
    expect(mockWriteText.mock.calls[0][0]).toContain('Re-rank the roadmap')
  })
})

describe('RoadmapView.vue — WS live refresh + indicator (FE-6022c)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: { product_id: 'prod-1', roadmap: null, items: ITEMS.map((i) => ({ ...i })) } })
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockResolvedValue() }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
  })

  it('subscribes to roadmap:updated on mount', async () => {
    await mountView()
    expect(mockWsOn).toHaveBeenCalledWith('roadmap:updated', expect.any(Function))
    expect(typeof wsHandlers['roadmap:updated']).toBe('function')
  })

  // FE-6240: the spinner is now raised by the agent's first roadmap-tool touch
  // (roadmap:agent_active WS event), not by the user's copy-prompt click.
  it('subscribes to roadmap:agent_active on mount', async () => {
    await mountView()
    expect(mockWsOn).toHaveBeenCalledWith('roadmap:agent_active', expect.any(Function))
    expect(typeof wsHandlers['roadmap:agent_active']).toBe('function')
  })

  it('a roadmap:agent_active event raises the waiting spinner', async () => {
    const w = await mountView()
    expect(w.vm.waiting).toBe(false)
    wsHandlers['roadmap:agent_active']({ product_id: 'prod-1' }) // agent connected
    expect(w.vm.waiting).toBe(true)
  })

  // TSK-6243: the spinner must survive a browser reload while an agent is mid-build.
  it('re-raises the spinner on remount when agent_active landed within the window', async () => {
    const first = await mountView()
    wsHandlers['roadmap:agent_active']({ product_id: 'prod-1' }) // agent connected -> stamp persisted
    expect(first.vm.waiting).toBe(true)
    first.unmount() // browser reload drops the in-memory spinner

    const second = await mountView() // fresh mount reads the persisted stamp
    expect(second.vm.waiting).toBe(true) // continuity restored
  })

  it('does NOT re-raise the spinner on mount when the persisted stamp is stale', async () => {
    localStorage.setItem('giljo.roadmap.agentActiveAt.prod-1', String(Date.now() - 200000)) // > 150s window
    const w = await mountView()
    expect(w.vm.waiting).toBe(false) // outside the window -> no spurious spinner
    expect(localStorage.getItem('giljo.roadmap.agentActiveAt.prod-1')).toBeNull() // stale stamp dropped
  })

  it('dismissWaiting clears the persisted stamp so a later reload stays clean', async () => {
    const first = await mountView()
    wsHandlers['roadmap:agent_active']({ product_id: 'prod-1' })
    expect(localStorage.getItem('giljo.roadmap.agentActiveAt.prod-1')).not.toBeNull()

    first.vm.dismissWaiting() // agent saved / user dismissed
    expect(localStorage.getItem('giljo.roadmap.agentActiveAt.prod-1')).toBeNull()
    first.unmount()

    const second = await mountView()
    expect(second.vm.waiting).toBe(false) // no leftover stamp -> no spinner
  })

  it('copyRoadmapPrompt does NOT raise the spinner (trigger is the agent, not the copy)', async () => {
    const w = await mountView()
    await w.vm.copyRoadmapPrompt()
    expect(w.vm.waiting).toBe(false)
  })

  it('a roadmap:updated event re-fetches (debounced) and clears the waiting indicator', async () => {
    const w = await mountView()
    wsHandlers['roadmap:agent_active']({ product_id: 'prod-1' }) // agent connected -> spinner up
    expect(w.vm.waiting).toBe(true)

    mockGet.mockClear()
    vi.useFakeTimers()
    wsHandlers['roadmap:updated']() // agent write arrives over WS
    vi.advanceTimersByTime(600) // debounce window
    vi.useRealTimers()
    await flushPromises()

    expect(mockGet).toHaveBeenCalledTimes(1) // live re-fetch
    expect(w.vm.waiting).toBe(false) // indicator WS-cleared
  })

  it('debounces a multi-write burst into a single re-fetch', async () => {
    const w = await mountView()
    mockGet.mockClear()
    vi.useFakeTimers()
    w.vm.onRoadmapUpdated()
    vi.advanceTimersByTime(200)
    w.vm.onRoadmapUpdated()
    vi.advanceTimersByTime(200)
    w.vm.onRoadmapUpdated()
    vi.advanceTimersByTime(600)
    vi.useRealTimers()
    await flushPromises()
    expect(mockGet).toHaveBeenCalledTimes(1) // collapsed to one
  })

  it('auto-clears the indicator after the safety timeout', async () => {
    const w = await mountView()
    vi.useFakeTimers()
    w.vm.onAgentActive() // agent connected -> sets waiting + the fake-timer safety timeout
    expect(w.vm.waiting).toBe(true)
    vi.advanceTimersByTime(150000)
    vi.useRealTimers()
    expect(w.vm.waiting).toBe(false)
  })

  it('a manual dismiss clears the indicator', async () => {
    const w = await mountView()
    w.vm.onAgentActive()
    expect(w.vm.waiting).toBe(true)
    w.vm.dismissWaiting()
    expect(w.vm.waiting).toBe(false)
  })

  // D3 (Headless S3a): a project staged/launched entirely via the MCP harness
  // (no dashboard tab open) never emitted project_update, so the roadmap card's
  // status badge went stale until the user navigated away and back.
  it('subscribes to project:staging_complete on mount', async () => {
    await mountView()
    expect(mockWsOn).toHaveBeenCalledWith('project:staging_complete', expect.any(Function))
    expect(typeof wsHandlers['project:staging_complete']).toBe('function')
  })

  it('subscribes to project:implementation_launched on mount', async () => {
    await mountView()
    expect(mockWsOn).toHaveBeenCalledWith('project:implementation_launched', expect.any(Function))
    expect(typeof wsHandlers['project:implementation_launched']).toBe('function')
  })

  it('a project:staging_complete event re-fetches (debounced)', async () => {
    await mountView()
    mockGet.mockClear()
    vi.useFakeTimers()
    wsHandlers['project:staging_complete']({ project_id: 'pa' })
    vi.advanceTimersByTime(600)
    vi.useRealTimers()
    await flushPromises()
    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  it('a project:implementation_launched event re-fetches (debounced)', async () => {
    await mountView()
    mockGet.mockClear()
    vi.useFakeTimers()
    wsHandlers['project:implementation_launched']({ project_id: 'pa' })
    vi.advanceTimersByTime(600)
    vi.useRealTimers()
    await flushPromises()
    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  it('defers a WS re-fetch while a reorder PATCH is in flight (isPersisting guard)', async () => {
    const w = await mountView()
    mockGet.mockClear()
    w.vm.isPersisting = true // simulate an in-flight optimistic reorder
    vi.useFakeTimers()
    w.vm.onRoadmapUpdated()
    vi.advanceTimersByTime(600) // first debounce fires -> sees guard -> re-arms
    await flushPromises()
    expect(mockGet).not.toHaveBeenCalled() // refetch deferred, optimistic order safe

    w.vm.isPersisting = false
    vi.advanceTimersByTime(600) // re-armed debounce fires
    vi.useRealTimers()
    await flushPromises()
    expect(mockGet).toHaveBeenCalledTimes(1) // now it re-fetches
  })
})

// ── status-sync regression (fix/roadmap-card-status-sync) ────────────────────
// Bug: RoadmapView only subscribed to roadmap:updated, so a project deactivated
// OUTSIDE the roadmap (project list or agent) while the view was mounted left
// the card's local ref stale: status stayed 'active' → card stayed LOCKED.
// Fix: also subscribe to project_update (the WS event project lifecycle fires
// for status_changed / deactivated) and call the existing debounced fetchRoadmap.
describe('RoadmapView.vue — project status-sync from external deactivation', () => {
  // Item 'a' starts with status 'active' (the locked/terminal state to clear).
  const ACTIVE_ITEMS = [
    { ...ITEMS[0], status: 'active', project_id: 'pa' },
    { ...ITEMS[1] },
    { ...ITEMS[2] },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    // Initial fetch: item 'a' is active (locked).
    mockGet.mockResolvedValueOnce({
      data: { product_id: 'prod-1', roadmap: null, items: ACTIVE_ITEMS.map((i) => ({ ...i })) },
    })
  })

  it('subscribes to project_update on mount (alongside roadmap:updated)', async () => {
    await mountView()
    expect(mockWsOn).toHaveBeenCalledWith('project_update', expect.any(Function))
    expect(typeof wsHandlers['project_update']).toBe('function')
  })

  it('a project_update status_changed event triggers a debounced re-fetch', async () => {
    const w = await mountView()
    // After the re-fetch the backend returns the card as inactive (no longer locked).
    mockGet.mockResolvedValueOnce({
      data: {
        product_id: 'prod-1',
        roadmap: null,
        items: [{ ...ACTIVE_ITEMS[0], status: 'inactive' }, ...ACTIVE_ITEMS.slice(1)],
      },
    })
    mockGet.mockClear() // clear the initial mount call count

    vi.useFakeTimers()
    // Simulate the WS event the project lifecycle service broadcasts on deactivation.
    wsHandlers['project_update']({ project_id: 'pa', update_type: 'status_changed', status: 'inactive' })
    vi.advanceTimersByTime(600) // debounce window
    vi.useRealTimers()
    await flushPromises()

    expect(mockGet).toHaveBeenCalledTimes(1) // exactly one re-fetch
    // Card is now 'inactive' — no longer active/locked.
    expect(w.vm.items[0].status).toBe('inactive')
  })

  it('a project_update deactivated event also triggers a debounced re-fetch', async () => {
    await mountView()
    mockGet.mockResolvedValueOnce({
      data: {
        product_id: 'prod-1',
        roadmap: null,
        items: [{ ...ACTIVE_ITEMS[0], status: 'inactive' }, ...ACTIVE_ITEMS.slice(1)],
      },
    })
    mockGet.mockClear()

    vi.useFakeTimers()
    wsHandlers['project_update']({ project_id: 'pa', update_type: 'deactivated' })
    vi.advanceTimersByTime(600)
    vi.useRealTimers()
    await flushPromises()

    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  it('a project_update "updated" event (rename) triggers a debounced re-fetch of live title/alias', async () => {
    // Bug-2 (alias 0005): a project renamed OUTSIDE the roadmap fires
    // project_update with update_type 'updated'. The backend joins title +
    // taxonomy_alias live, so the card must re-fetch to drop the stale name —
    // previously 'updated' was filtered out and the old name/alias persisted.
    const w = await mountView()
    // After the re-fetch the backend returns the renamed title + new alias.
    mockGet.mockResolvedValueOnce({
      data: {
        product_id: 'prod-1',
        roadmap: null,
        items: [
          { ...ACTIVE_ITEMS[0], title: 'Renamed', taxonomy_alias: 'FE-0013' },
          ...ACTIVE_ITEMS.slice(1),
        ],
      },
    })
    mockGet.mockClear()

    vi.useFakeTimers()
    wsHandlers['project_update']({ project_id: 'pa', update_type: 'updated' })
    vi.advanceTimersByTime(600) // debounce window
    vi.useRealTimers()
    await flushPromises()

    expect(mockGet).toHaveBeenCalledTimes(1) // exactly one re-fetch
    expect(w.vm.items[0].title).toBe('Renamed')
    expect(w.vm.items[0].taxonomy_alias).toBe('FE-0013')
  })

  it('project_update events from status_changed are debounced (burst → single fetch)', async () => {
    const w = await mountView()
    mockGet.mockResolvedValue({
      data: { product_id: 'prod-1', roadmap: null, items: ACTIVE_ITEMS.map((i) => ({ ...i })) },
    })
    mockGet.mockClear()

    vi.useFakeTimers()
    // Three rapid status events — only one fetch should result.
    wsHandlers['project_update']({ project_id: 'pa', update_type: 'status_changed', status: 'inactive' })
    vi.advanceTimersByTime(100)
    wsHandlers['project_update']({ project_id: 'pb', update_type: 'status_changed', status: 'active' })
    vi.advanceTimersByTime(100)
    wsHandlers['project_update']({ project_id: 'pa', update_type: 'deactivated' })
    vi.advanceTimersByTime(600) // let final debounce settle
    vi.useRealTimers()
    await flushPromises()

    expect(mockGet).toHaveBeenCalledTimes(1) // collapsed — not 3

    // Silence unused-variable lint (w is mounted to exercise the full lifecycle).
    expect(w.vm.items).toBeDefined()
  })

  // FE-9568 (2026-09-02, operator ruling): the roadmap-card Deactivate button
  // (and its RoadmapView `deactivate()` handler, which called
  // projectStore.deactivateProject then fetchRoadmap directly) is REMOVED —
  // /roadmap only orders work now. A project deactivated from elsewhere
  // (Projects page, an agent) still reaches this view live via the
  // project_update subscription pinned by the tests above; this test used to
  // pin the OTHER path (deactivating FROM /roadmap itself), which no longer
  // exists, so it is replaced with an absence assertion instead of deleted.
  it('no longer exposes a deactivate() handler — that control was removed', async () => {
    const w = await mountView()
    expect(w.vm.deactivate).toBeUndefined()
    expect(w.vm.activate).toBeUndefined()
  })
})

// FE-9407: the waiting spinner must not survive its own success.
// The RAISE is durable (a localStorage stamp, re-raised on remount) but the
// CLEAR was a one-shot WS event consumed only while mounted — so a save that
// landed while RoadmapView was unmounted, or behind a dead socket, left the
// spinner re-raising over freshly rendered rows until the safety timeout.
// roadmap.last_generated_at is the durable record of that save; these cases pin
// the reconciliation against it, in BOTH directions (it must clear a spinner
// the agent already answered, and must NOT clear one still legitimately up).
const STAMP_KEY = 'giljo.roadmap.agentActiveAt.prod-1'

function roadmapResponse(lastGeneratedAt, items = ITEMS) {
  return {
    data: {
      product_id: 'prod-1',
      roadmap: { summary: null, last_generated_at: lastGeneratedAt },
      items: items.map((i) => ({ ...i })),
    },
  }
}

describe('RoadmapView.vue — waiting-spinner reconciliation (FE-9407)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resyncCallbacks.length = 0
    mockGet.mockResolvedValue(roadmapResponse(null))
  })

  it('does NOT re-raise the spinner on mount when the agent saved after the stamp', async () => {
    // The agent connected 60s ago (stamp well inside the 150s window) and saved
    // 10s ago while the view was unmounted, so the single clear broadcast was
    // lost. The mount re-fetch renders those saved rows.
    localStorage.setItem(STAMP_KEY, String(Date.now() - 60000))
    mockGet.mockResolvedValue(roadmapResponse(new Date(Date.now() - 10000).toISOString()))

    const w = await mountView()

    expect(w.vm.waiting).toBe(false) // the wait is over — the roadmap is on screen
    expect(localStorage.getItem(STAMP_KEY)).toBeNull() // superseded stamp dropped
  })

  it('STILL re-raises the spinner when the last save predates the stamp (TSK-6243 mid-build reload)', async () => {
    // The roadmap was last saved long before this build started, so the agent is
    // still working: reload continuity must survive the reconciliation.
    localStorage.setItem(STAMP_KEY, String(Date.now() - 60000))
    mockGet.mockResolvedValue(roadmapResponse(new Date(Date.now() - 600000).toISOString()))

    const w = await mountView()

    expect(w.vm.waiting).toBe(true)
    expect(localStorage.getItem(STAMP_KEY)).not.toBeNull()
  })

  it('does NOT clear on a save that beats the stamp by less than the clock-skew margin', async () => {
    // The stamp is a client Date.now() and the save is server UTC, so a
    // sub-margin difference is skew, not a save, and must not take the
    // spinner down.
    const stampedAt = Date.now() - 60000
    localStorage.setItem(STAMP_KEY, String(stampedAt))
    mockGet.mockResolvedValue(roadmapResponse(new Date(stampedAt + 2000).toISOString()))

    const w = await mountView()

    expect(w.vm.waiting).toBe(true)
  })

  it('does NOT clear on a newer save when the roadmap came back empty', async () => {
    localStorage.setItem(STAMP_KEY, String(Date.now() - 60000))
    mockGet.mockResolvedValue(roadmapResponse(new Date(Date.now() - 10000).toISOString(), []))

    const w = await mountView()

    expect(w.vm.waiting).toBe(true) // nothing delivered yet — still genuinely waiting
  })

  it('a WS reconnect clears a spinner whose clear was lost behind a dead socket', async () => {
    // Mid-build reload: stamp inside the window, last save predates it, so the
    // spinner is legitimately up.
    localStorage.setItem(STAMP_KEY, String(Date.now() - 60000))
    mockGet.mockResolvedValue(roadmapResponse(new Date(Date.now() - 600000).toISOString()))
    const w = await mountView()
    expect(w.vm.waiting).toBe(true)
    expect(resyncCallbacks).toHaveLength(1)

    // The agent saved while the socket was dead, so no roadmap:updated ever
    // arrived. The reconnect resync re-reads the roadmap and reconciles —
    // note the spinner is ALREADY up here, which is why this path needs the
    // reconciliation itself and not the mount-time rehydrate.
    mockGet.mockResolvedValue(roadmapResponse(new Date(Date.now() - 5000).toISOString()))
    await resyncCallbacks[0]()
    await flushPromises()

    expect(w.vm.waiting).toBe(false)
    expect(localStorage.getItem(STAMP_KEY)).toBeNull()
  })

  it('a WS reconnect mid-build re-fetches but LEAVES the spinner up', async () => {
    // The discriminating case: a reconnect that dismissed unconditionally would
    // satisfy the test above too. Here the agent is still working (the last save
    // predates the stamp), so the reconnect must re-read and change nothing.
    localStorage.setItem(STAMP_KEY, String(Date.now() - 60000))
    mockGet.mockResolvedValue(roadmapResponse(new Date(Date.now() - 600000).toISOString()))
    const w = await mountView()
    expect(w.vm.waiting).toBe(true)

    mockGet.mockClear()
    await resyncCallbacks[0]()
    await flushPromises()

    expect(mockGet).toHaveBeenCalled() // the roadmap IS re-read on reconnect
    expect(w.vm.waiting).toBe(true) // ...and the agent is still working
    expect(localStorage.getItem(STAMP_KEY)).not.toBeNull()
  })

  // ── FE-9553: fetchRoadmap is silent unless a click asked for it ───────────
  //
  // This is the worst of the dual-reachable cases: fetchRoadmap runs from
  // onMounted, from a debounced WebSocket refetch when an agent renames or
  // deactivates a project, and from four separate user actions. A toast on
  // either background path announces somebody else's work as though the
  // operator had just done it.
  //
  // Both directions are asserted deliberately. A silence test alone would
  // pass just as happily if the guard were always off and the toast
  // unreachable from anywhere.
  describe('the notify opt-in (FE-9553)', () => {
    it('says NOTHING when the mount-time load fails', async () => {
      mockGet.mockRejectedValue(new Error('network'))
      showToastSpy.mockClear()

      await mountView()

      expect(showToastSpy).not.toHaveBeenCalled()
    })

    it('says NOTHING when the WS-driven refetch fails', async () => {
      mockGet.mockResolvedValue(roadmapResponse())
      const w = await mountView()
      mockGet.mockRejectedValue(new Error('network'))
      showToastSpy.mockClear()

      // The bare call is what every background path makes.
      await w.vm.fetchRoadmap()
      await flushPromises()

      expect(showToastSpy).not.toHaveBeenCalled()
    })

    it('DOES speak up when a click asked for the refetch', async () => {
      // The positive control. Without it the two silences above would be
      // satisfied by a guard that is simply always off.
      mockGet.mockResolvedValue(roadmapResponse())
      const w = await mountView()
      mockGet.mockRejectedValue(new Error('network'))
      showToastSpy.mockClear()

      await w.vm.fetchRoadmap({ notify: true })
      await flushPromises()

      expect(showToastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'error' }),
      )
    })
  })
})
