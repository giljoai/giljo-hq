import { describe, it, expect, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { useProjectFilters, ARCHIVED_STATUS } from './useProjectFilters'
import { useTaskFilters, ARCHIVED_FILTER } from './useTaskFilters'

describe('Projects: the Archived entry in the status multi-select', () => {
  let make

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
    const activeProduct = ref({ id: 'prod-1' })
    const projectStatuses = ref([
      { value: 'inactive', label: 'Inactive' },
      { value: 'active', label: 'Active' },
      { value: 'completed', label: 'Completed' },
      { value: 'deleted', label: 'Deleted' },
    ])
    const hiddenProjects = ref([
      { id: 'h1', product_id: 'prod-1', deleted_at: null },
      { id: 'h2', product_id: 'prod-1', deleted_at: null },
      { id: 'other', product_id: 'prod-2', deleted_at: null },
    ])
    make = () => useProjectFilters({ activeProduct, projectStatuses, hiddenProjects })
  })

  it('is the last option and carries the archived count for this product', () => {
    const { statusSelectOptions } = make()
    expect(statusSelectOptions.value.at(-1)).toEqual({ title: 'Archived (2)', value: ARCHIVED_STATUS })
  })

  it('is not part of the default selection (archived rows stay out of the default list)', async () => {
    const { selectedStatuses, buildServerParams } = make()
    await nextTick()
    expect(selectedStatuses.value).not.toContain(ARCHIVED_STATUS)
    expect(buildServerParams().includeHidden).toBeUndefined()
  })

  it('ticked alongside statuses: adds archived rows, and is never sent as a status', async () => {
    const { selectedStatuses, buildServerParams } = make()
    await nextTick()
    selectedStatuses.value = ['inactive', ARCHIVED_STATUS]
    const params = buildServerParams()
    expect(params.statuses).toEqual(['inactive'])
    expect(params.includeHidden).toBe(true)
    expect(params.hiddenOnly).toBeUndefined()
  })

  it('ticked alone: the Archived view, only archived rows across every status', async () => {
    const { selectedStatuses, buildServerParams } = make()
    await nextTick()
    selectedStatuses.value = [ARCHIVED_STATUS]
    const params = buildServerParams()
    expect(params.statuses).toBeUndefined()
    expect(params.hiddenOnly).toBe(true)
    expect(params.includeCompleted).toBe(true)
  })
})

describe('Tasks: the Archived entry in the status filter', () => {
  const tasks = ref([
    { id: 't1', title: 'Open', status: 'pending', hidden: false },
    { id: 't2', title: 'Old', status: 'completed', hidden: true },
    { id: 't3', title: 'Older', status: 'pending', hidden: true },
  ])

  it('is offered in the filter dropdown with its count, but never as a task status', () => {
    const { statusFilterOptions, statusSelectOptions } = useTaskFilters(tasks)
    expect(statusFilterOptions.value.at(-1)).toEqual({ title: 'Archived (2)', value: ARCHIVED_FILTER })
    expect(statusSelectOptions.value.map((o) => o.value)).not.toContain(ARCHIVED_FILTER)
  })

  it('shows only archived tasks when picked', () => {
    const { statusFilter, filteredTasks } = useTaskFilters(tasks)
    expect(filteredTasks.value.map((t) => t.id)).toEqual(['t1'])
    statusFilter.value = ARCHIVED_FILTER
    expect(filteredTasks.value.map((t) => t.id)).toEqual(['t2', 't3'])
  })
})
