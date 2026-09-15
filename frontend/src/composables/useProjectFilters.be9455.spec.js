import { describe, it, expect, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useProjectFilters } from './useProjectFilters'

const API_LIMIT_MIN = 1
const API_LIMIT_MAX = 200

describe('BE-9455 — the per-page control must emit a limit the API accepts', () => {
  let activeProduct
  let projectStatuses
  let hiddenProjects
  let showHidden

  beforeEach(() => {
    const store = new Map()
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, String(v)),
        removeItem: (k) => store.delete(k),
        clear: () => store.clear(),
      },
      writable: true,
      configurable: true,
    })
    activeProduct = ref({ id: 'prod-1', name: 'Test Product' })
    projectStatuses = ref([
      { value: 'inactive', label: 'Inactive' },
      { value: 'active', label: 'Active' },
      { value: 'completed', label: 'Completed' },
      { value: 'cancelled', label: 'Cancelled' },
      { value: 'terminated', label: 'Terminated' },
      { value: 'deleted', label: 'Deleted' },
    ])
    hiddenProjects = ref([])
    showHidden = ref(false)
  })

  const make = () => useProjectFilters({ activeProduct, projectStatuses, hiddenProjects, showHidden })

  it('does not emit the Vuetify "All" sentinel (-1) as the server limit', () => {
    const f = make()
    f.itemsPerPage.value = -1

    const params = f.buildServerParams()

    expect(params.limit).toBeGreaterThanOrEqual(API_LIMIT_MIN)
    expect(params.limit).toBeLessThanOrEqual(API_LIMIT_MAX)
  })

  it('emits a non-negative offset when the per-page control is "All"', () => {
    const f = make()
    f.itemsPerPage.value = -1
    f.currentPage.value = 2

    expect(f.buildServerParams().offset).toBeGreaterThanOrEqual(0)
  })

  it('leaves the ordinary numeric page sizes untouched', () => {
    const f = make()
    for (const size of [10, 25, 50, 100]) {
      f.itemsPerPage.value = size
      f.currentPage.value = 1
      expect(f.buildServerParams().limit).toBe(size)
    }
  })

  it('still pages correctly at the sizes the operator currently works around with', () => {
    const f = make()
    f.itemsPerPage.value = 100
    f.currentPage.value = 3
    const params = f.buildServerParams()
    expect(params.limit).toBe(100)
    expect(params.offset).toBe(200)
  })

  it.each([
    ['the Vuetify "All" sentinel', -1],
    ['zero', 0],
    ['one past the API cap', 201],
    ['a wildly oversized page', 9999],
    ['another negative sentinel', -10],
  ])('resolves %s to an in-contract limit', (_label, size) => {
    const f = make()
    f.itemsPerPage.value = size
    f.currentPage.value = 4

    const params = f.buildServerParams()

    expect(params.limit).toBeGreaterThanOrEqual(API_LIMIT_MIN)
    expect(params.limit).toBeLessThanOrEqual(API_LIMIT_MAX)
    expect(params.offset).toBeGreaterThanOrEqual(0)
    expect(Number.isInteger(params.offset)).toBe(true)
  })

  it('derives offset from the CLAMPED size, so paging stays consistent with it', () => {
    const f = make()
    f.itemsPerPage.value = 500
    f.currentPage.value = 3

    const params = f.buildServerParams()

    expect(params.limit).toBe(API_LIMIT_MAX)
    expect(params.offset).toBe(2 * API_LIMIT_MAX)
  })
})
