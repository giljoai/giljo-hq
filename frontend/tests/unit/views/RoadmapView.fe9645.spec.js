/**
 * RoadmapView.vue — FE-9645 roadmap insight banner
 *
 * The AI-insight banner (sourced from roadmap.summary) must:
 *   - stay HIDDEN when the roadmap has zero items, even if a stale summary
 *     is still present on the roadmap row;
 *   - show a title "Why this order · <locale date>" when
 *     roadmap.last_generated_at is set;
 *   - show the title "Why this order" (no date) when last_generated_at is null.
 *
 * Edition Scope: Both.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const { mockGet, mockReorder, mockRemoveItem } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockReorder: vi.fn().mockResolvedValue({ data: {} }),
  mockRemoveItem: vi.fn().mockResolvedValue({ data: { removed: 1 } }),
}))

vi.mock('@/services/api', () => {
  const svc = {
    roadmap: { get: mockGet, reorder: mockReorder, removeItem: mockRemoveItem },
    taxonomyTypes: { list: vi.fn().mockResolvedValue({ data: [] }) },
    tasks: { get: vi.fn().mockResolvedValue({ data: {} }) },
  }
  return { default: svc, api: svc }
})

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    currentProduct: { id: 'prod-1', name: 'Test Product' },
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
  useWebSocketStore: () => ({ on: vi.fn(() => () => {}) }),
}))

vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: vi.fn(() => () => {}),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
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

vi.mock('vuedraggable', () => ({
  default: {
    name: 'draggable',
    props: { modelValue: { type: Array, default: () => [] } },
    emits: ['update:modelValue'],
    template: '<div class="vdraggable" />',
  },
}))

import RoadmapView from '@/views/RoadmapView.vue'

const ITEM = {
  id: 'a',
  item_type: 'project',
  project_id: 'pa',
  task_id: null,
  title: 'A',
  taxonomy_alias: 'BE-0001',
  sort_order: 0,
  risk: 'low',
  complexity: 'heavy',
}

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

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('RoadmapView.vue — FE-9645 insight banner', () => {
  it('stays hidden when the roadmap has zero items, even with a stale summary', async () => {
    mockGet.mockResolvedValue({
      data: {
        product_id: 'prod-1',
        roadmap: { summary: 'Stale reasoning from a deleted plan.', last_generated_at: '2026-09-20T10:00:00Z' },
        items: [],
      },
    })
    const w = await mountView()
    expect(w.find('.rm-insight').exists()).toBe(false)
    expect(w.text()).not.toContain('Stale reasoning from a deleted plan.')
  })

  it('shows "Why this order · <date>" when last_generated_at is set', async () => {
    mockGet.mockResolvedValue({
      data: {
        product_id: 'prod-1',
        roadmap: { summary: 'Ships the riskiest item first.', last_generated_at: '2026-09-20T10:00:00Z' },
        items: [{ ...ITEM }],
      },
    })
    const w = await mountView()
    const banner = w.find('.rm-insight')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('Why this order · Sep 20, 2026')
    expect(banner.text()).toContain('Ships the riskiest item first.')
  })

  it('shows "Why this order" with no date when last_generated_at is null', async () => {
    mockGet.mockResolvedValue({
      data: {
        product_id: 'prod-1',
        roadmap: { summary: 'Ships the riskiest item first.', last_generated_at: null },
        items: [{ ...ITEM }],
      },
    })
    const w = await mountView()
    const banner = w.find('.rm-insight')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('Why this order')
    expect(banner.text()).not.toContain('Why this order ·')
  })
})
