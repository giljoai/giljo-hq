/**
 * useProjectFilters.be9455.spec.js — BE-9455: the per-page "All" control.
 *
 * Edition Scope: Both.
 *
 * THE DEFECT, at the layer it lives in. Vuetify's `v-data-table-server` footer
 * ships a default per-page option list ending in `{ value: -1, title: 'All' }`
 * (vuetify 4.1.5, VDataTableFooter.js). `ProjectsTable.vue` renders that default,
 * so selecting "All" sets `itemsPerPage` to the sentinel `-1`, which
 * `buildServerParams()` forwards verbatim as `limit: -1`.
 *
 * `GET /api/v1/projects/` declares `limit: int | None = Query(ge=1, le=200)`
 * (api/endpoints/projects/crud.py). A `-1` is therefore rejected with HTTP 422
 * before the query runs, `projectStore.fetchProjects` swallows it into
 * `error.value`, and the table never changes — the operator's report that "All
 * does not expand the list".
 *
 * These tests assert the CONTRACT rather than the widget: whatever the per-page
 * control is set to, the emitted `limit`/`offset` must be values the API will
 * accept. That keeps the assertion true no matter how the option list is later
 * re-specified, which is the point — a control must not promise what the wire
 * cannot carry.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useProjectFilters } from './useProjectFilters'

// The bounds declared by `limit` on GET /api/v1/projects/ (crud.py). Mirrored
// here deliberately: if the endpoint's bounds move, this spec must be updated
// alongside, and the matching backend test pins the same pair from the API side.
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
    // What v-data-table-server reports upward when the user picks "All".
    f.itemsPerPage.value = -1

    const params = f.buildServerParams()

    expect(params.limit).toBeGreaterThanOrEqual(API_LIMIT_MIN)
    expect(params.limit).toBeLessThanOrEqual(API_LIMIT_MAX)
  })

  it('emits a non-negative offset when the per-page control is "All"', () => {
    const f = make()
    f.itemsPerPage.value = -1
    f.currentPage.value = 2

    // offset = (page - 1) * itemsPerPage — with the sentinel that is negative,
    // and `offset` is declared ge=0 on the endpoint, so it 422s on its own.
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

  // The fix clamps rather than special-casing the single `-1` sentinel, so the
  // whole CLASS of out-of-contract page sizes dies here — not just the one value
  // Vuetify happens to use today. A future option-list edit, a copied composable,
  // or a Vuetify default change cannot reintroduce a request the API will reject.
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
    // An over-cap request collapses to the cap; page 3 must then start at 2*cap,
    // not at 2*the-requested-size, or the pages would overlap or skip rows.
    f.itemsPerPage.value = 500
    f.currentPage.value = 3

    const params = f.buildServerParams()

    expect(params.limit).toBe(API_LIMIT_MAX)
    expect(params.offset).toBe(2 * API_LIMIT_MAX)
  })
})
