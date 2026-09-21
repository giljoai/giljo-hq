import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'

const { mockGet, mockReorder, mockRemoveItem, productState } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockReorder: vi.fn().mockResolvedValue({ data: {} }),
  mockRemoveItem: vi.fn().mockResolvedValue({ data: { removed: 1 } }),
  productState: { current: null },
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
  useProductStore: () => productState.current,
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

const PRODUCT_A = { id: 'prod-a', name: 'Waypost' }
const PRODUCT_B = { id: 'prod-b', name: 'Default Product' }

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

function roadmapFor(productId) {
  if (productId === PRODUCT_B.id) {
    return {
      data: {
        product_id: PRODUCT_B.id,
        roadmap: { summary: 'B default summary' },
        items: [
          { id: 'b1', item_type: 'project', project_id: 'pb', task_id: null, title: 'B1', taxonomy_alias: 'BE-0001', sort_order: 0, risk: 'low', complexity: 'light' },
        ],
      },
    }
  }
  return { data: { product_id: PRODUCT_A.id, roadmap: null, items: [] } }
}

beforeEach(() => {
  vi.clearAllMocks()
  productState.current = reactive({
    currentProduct: PRODUCT_B,
    activeProduct: PRODUCT_B,
    effectiveProductId: PRODUCT_B.id,
    fetchActiveProduct: vi.fn().mockResolvedValue(),
  })
  mockGet.mockImplementation((productId) => Promise.resolve(roadmapFor(productId)))
})

afterEach(() => {
  productState.current = null
})

describe('RoadmapView.vue -- BE-9623 follows the viewed product tab', () => {
  it('the initial GET carries the viewed product id', async () => {
    productState.current.currentProduct = PRODUCT_A
    const w = mount(RoadmapView, { global: { stubs } })
    await flushPromises()

    expect(mockGet).toHaveBeenCalled()
    expect(mockGet.mock.calls.every((call) => call[0] === PRODUCT_A.id)).toBe(true)
    expect(w.vm.items).toEqual([])
    expect(w.text()).not.toContain('B default summary')
  })

  it('switching the viewed product clears the old roadmap and refetches scoped to the new one', async () => {
    const w = mount(RoadmapView, { global: { stubs } })
    await flushPromises()
    expect(w.vm.items.map((i) => i.id)).toEqual(['b1'])
    expect(w.text()).toContain('B default summary')

    mockGet.mockClear()
    productState.current.currentProduct = PRODUCT_A
    await flushPromises()

    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet).toHaveBeenCalledWith(PRODUCT_A.id)
    expect(w.vm.items).toEqual([])
    expect(w.text()).not.toContain('B default summary')
  })
})
