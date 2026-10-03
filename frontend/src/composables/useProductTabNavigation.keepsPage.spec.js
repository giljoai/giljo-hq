import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  route: { name: 'JobsViewport', params: {}, query: {} },
  list: vi.fn(),
  get: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push }),
  useRoute: () => h.route,
}))

vi.mock('@/services/api', () => ({
  default: { products: { list: (...a) => h.list(...a), get: (...a) => h.get(...a) } },
}))

import { useProductTabNavigation } from './useProductTabNavigation'
import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useCommHubStore } from '@/stores/commHubStore'

const PRODUCTS = [
  { id: 'prod-a', name: 'A', is_active: true },
  { id: 'prod-b', name: 'B', is_active: true },
]

let productStore
let projectStore
let taskStore

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  h.list.mockResolvedValue({ data: PRODUCTS })
  h.get.mockImplementation(async (id) => ({ data: PRODUCTS.find((p) => p.id === id) }))
  productStore = useProductStore()
  projectStore = useProjectStore()
  taskStore = useTaskStore()
  projectStore.fetchProjects = vi.fn()
  taskStore.fetchTasks = vi.fn()
  useCommHubStore().loadThreads = vi.fn()
  productStore.currentProductId = 'prod-a'
})

describe('a product switch keeps the current page', () => {
  it.each([
    'JobsViewport',
    'Tasks',
    'Roadmap',
    'Projects',
    'Home',
    'Hub',
    'MemoryBrowser',
    'Dashboard',
  ])('stays on %s and re-scopes its data to the new product', async (name) => {
    h.route = { name, params: {}, query: {} }

    await useProductTabNavigation().selectTab('prod-b')

    expect(h.push).not.toHaveBeenCalled()
    expect(productStore.effectiveProductId).toBe('prod-b')
    expect(projectStore.fetchProjects).toHaveBeenCalled()
    expect(taskStore.fetchTasks).toHaveBeenCalledWith({ product_id: 'prod-b' })
  })
})

describe('a product detail page follows the switch', () => {
  it('opens the new product’s detail page from another product’s detail page', async () => {
    h.route = { name: 'ProductDetail', params: { id: 'prod-a' }, query: {} }

    await useProductTabNavigation().selectTab('prod-b')

    expect(h.push).toHaveBeenCalledWith({ name: 'ProductDetail', params: { id: 'prod-b' } })
  })

  it('stays put when the detail page already shows the product switched to', async () => {
    h.route = { name: 'ProductDetail', params: { id: 'prod-b' }, query: {} }

    await useProductTabNavigation().selectTab('prod-b')

    expect(h.push).not.toHaveBeenCalled()
  })
})
