import { describe, it, expect, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useTaskFilters } from './useTaskFilters'

describe('useTaskFilters', () => {
  const makeTasks = () => [
    {
      id: 1,
      title: 'Fix login bug',
      status: 'pending',
      priority: 'high',
      task_type: 'BE',
      task_type_id: 'type-be',
    },
    {
      id: 2,
      title: 'Add dashboard feature',
      status: 'in_progress',
      priority: 'medium',
      task_type: 'FE',
      task_type_id: 'type-fe',
    },
    {
      id: 3,
      title: 'Write docs',
      status: 'completed',
      priority: 'low',
      task_type: null,
      task_type_id: null,
    },
    {
      id: 4,
      title: 'Critical security patch',
      status: 'pending',
      priority: 'critical',
      task_type: 'BE',
      task_type_id: 'type-be',
    },
  ]

  let tasks

  beforeEach(() => {
    tasks = ref(makeTasks())
  })

  it('returns all tasks when no filters are applied', () => {
    const { filteredTasks } = useTaskFilters(tasks)
    expect(filteredTasks.value).toHaveLength(4)
  })

  it('filters by status', () => {
    const { filteredTasks, statusFilter } = useTaskFilters(tasks)
    statusFilter.value = 'pending'
    expect(filteredTasks.value).toHaveLength(2)
    expect(filteredTasks.value.every((t) => t.status === 'pending')).toBe(true)
  })

  it('filters by priority', () => {
    const { filteredTasks, priorityFilter } = useTaskFilters(tasks)
    priorityFilter.value = 'high'
    expect(filteredTasks.value).toHaveLength(1)
    expect(filteredTasks.value[0].id).toBe(1)
  })

  it('filters by search term (case-insensitive)', () => {
    const { filteredTasks, search } = useTaskFilters(tasks)
    search.value = 'login'
    expect(filteredTasks.value).toHaveLength(1)
    expect(filteredTasks.value[0].id).toBe(1)
  })

  it('combines multiple filters (status + priority)', () => {
    const { filteredTasks, statusFilter, priorityFilter } = useTaskFilters(tasks)
    statusFilter.value = 'pending'
    priorityFilter.value = 'critical'
    expect(filteredTasks.value).toHaveLength(1)
    expect(filteredTasks.value[0].id).toBe(4)
  })

  it('returns empty array when no tasks match', () => {
    const { filteredTasks, search } = useTaskFilters(tasks)
    search.value = 'nonexistent task xyz'
    expect(filteredTasks.value).toHaveLength(0)
  })

  it('clearFilters resets all filter state', () => {
    const { search, statusFilter, priorityFilter, clearFilters } =
      useTaskFilters(tasks)
    search.value = 'something'
    statusFilter.value = 'pending'
    priorityFilter.value = 'high'

    clearFilters()

    expect(search.value).toBe('')
    expect(statusFilter.value).toBeNull()
    expect(priorityFilter.value).toBeNull()
  })

  it('search filters by title', () => {
    const { filteredTasks, search } = useTaskFilters(tasks)
    search.value = 'DOCS'
    expect(filteredTasks.value).toHaveLength(1)
    expect(filteredTasks.value[0].id).toBe(3)
  })

  it('search matches by description (case-insensitive)', () => {
    const taggedTasks = ref([
      {
        id: 10,
        title: 'Reseed agents on activation',
        description: 'Activating a product should not re-run the agent seed.',
        status: 'pending',
        priority: 'medium',
        task_type_id: 'type-be',
        taxonomy_alias: 'BE5042',
        series_number: 5042,
      },
      {
        id: 11,
        title: 'Unrelated work',
        description: 'Nothing here.',
        status: 'pending',
        priority: 'low',
        task_type_id: null,
        taxonomy_alias: '',
        series_number: null,
      },
    ])
    const { filteredTasks, search } = useTaskFilters(taggedTasks)
    search.value = 'agent seed'
    expect(filteredTasks.value.map((t) => t.id)).toEqual([10])
  })

  it('search matches by taxonomy_alias (full serial badge)', () => {
    const taggedTasks = ref([
      {
        id: 20,
        title: 'A task',
        description: null,
        status: 'pending',
        priority: 'medium',
        task_type_id: 'type-fe',
        taxonomy_alias: 'FE5047',
        series_number: 5047,
      },
      {
        id: 21,
        title: 'Another task',
        description: null,
        status: 'pending',
        priority: 'medium',
        task_type_id: 'type-be',
        taxonomy_alias: 'BE5042',
        series_number: 5042,
      },
    ])
    const { filteredTasks, search } = useTaskFilters(taggedTasks)
    search.value = 'FE5047'
    expect(filteredTasks.value.map((t) => t.id)).toEqual([20])
  })

  it('search matches by partial serial number digits', () => {
    const taggedTasks = ref([
      {
        id: 30,
        title: 'A task',
        description: null,
        status: 'pending',
        priority: 'medium',
        task_type_id: 'type-be',
        taxonomy_alias: 'BE5042',
        series_number: 5042,
      },
      {
        id: 31,
        title: 'Another task',
        description: null,
        status: 'pending',
        priority: 'medium',
        task_type_id: 'type-fe',
        taxonomy_alias: 'FE5047',
        series_number: 5047,
      },
    ])
    const { filteredTasks, search } = useTaskFilters(taggedTasks)
    search.value = '5042'
    expect(filteredTasks.value.map((t) => t.id)).toEqual([30])
  })

  it('search does not throw on tasks with null description / empty alias', () => {
    const taggedTasks = ref([
      {
        id: 40,
        title: 'Untyped scratch note',
        description: null,
        status: 'pending',
        priority: 'low',
        task_type_id: null,
        taxonomy_alias: '',
        series_number: null,
      },
    ])
    const { filteredTasks, search } = useTaskFilters(taggedTasks)
    search.value = 'scratch'
    expect(filteredTasks.value.map((t) => t.id)).toEqual([40])
  })

  it('reacts to task list changes', () => {
    const { filteredTasks, statusFilter } = useTaskFilters(tasks)
    statusFilter.value = 'pending'
    expect(filteredTasks.value).toHaveLength(2)

    tasks.value = [
      { id: 5, title: 'New task', status: 'pending', priority: 'low', task_type_id: null },
    ]
    expect(filteredTasks.value).toHaveLength(1)
  })

  describe('statusSelectOptions', () => {
    it('exposes the six canonical task statuses (mirrors BE TaskUpdate enum)', () => {
      const { statusSelectOptions } = useTaskFilters(tasks)
      const values = statusSelectOptions.value.map((o) => o.value)
      expect(values).toEqual([
        'pending',
        'in_progress',
        'on_hold',
        'completed',
        'blocked',
        'cancelled',
      ])
    })

    it('offers On hold as a settable status and as a filter', () => {
      const { statusSelectOptions, statusFilterOptions, statusFilter, filteredTasks } = useTaskFilters(ref([
        { id: 1, title: 'parked', status: 'on_hold', priority: 'low', task_type_id: null },
        { id: 2, title: 'live', status: 'in_progress', priority: 'low', task_type_id: null },
      ]))
      expect(statusSelectOptions.value).toContainEqual({ title: 'On hold', value: 'on_hold' })
      expect(statusFilterOptions.value).toContainEqual({ title: 'On hold', value: 'on_hold' })
      statusFilter.value = 'on_hold'
      expect(filteredTasks.value.map((t) => t.id)).toEqual([1])
    })
  })

  describe('no task-type filter (FE-6049e)', () => {
    it('does not expose taskTypeFilter or typeSelectOptions', () => {
      const filters = useTaskFilters(tasks)
      expect(filters.taskTypeFilter).toBeUndefined()
      expect(filters.typeSelectOptions).toBeUndefined()
    })
  })

  describe('hidden task exclusion (IMP-5038)', () => {
    const makeHiddenTasks = () => [
      {
        id: 100,
        title: 'Visible task',
        description: 'shows by default',
        status: 'pending',
        priority: 'medium',
        task_type_id: 'type-be',
        taxonomy_alias: 'BE-0100',
        hidden: false,
      },
      {
        id: 101,
        title: 'Visible no-flag task',
        description: 'no hidden field at all',
        status: 'pending',
        priority: 'medium',
        task_type_id: 'type-be',
        taxonomy_alias: 'BE-0101',
      },
      {
        id: 102,
        title: 'Hidden archived task',
        description: 'should not appear by default',
        status: 'pending',
        priority: 'low',
        task_type_id: 'type-be',
        taxonomy_alias: 'BE-0102',
        hidden: true,
      },
    ]

    it('excludes tasks with hidden:true when search is empty', () => {
      const hiddenTasks = ref(makeHiddenTasks())
      const { filteredTasks } = useTaskFilters(hiddenTasks)
      const ids = filteredTasks.value.map((t) => t.id)
      expect(ids).toContain(100)
      expect(ids).toContain(101)
      expect(ids).not.toContain(102)
    })

    it('includes hidden tasks when search matches (search is nuclear)', () => {
      const hiddenTasks = ref(makeHiddenTasks())
      const { filteredTasks, search } = useTaskFilters(hiddenTasks)
      search.value = 'archived'
      const ids = filteredTasks.value.map((t) => t.id)
      expect(ids).toEqual([102])
    })

    it('does not affect non-hidden tasks (baseline)', () => {
      const hiddenTasks = ref(makeHiddenTasks())
      const { filteredTasks } = useTaskFilters(hiddenTasks)
      const visible = filteredTasks.value.filter((t) => !t.hidden)
      expect(visible).toHaveLength(2)
      expect(visible.map((t) => t.id).sort()).toEqual([100, 101])
    })

    it('showHidden defaults to false (archived excluded by default)', () => {
      const hiddenTasks = ref(makeHiddenTasks())
      const { showHidden } = useTaskFilters(hiddenTasks)
      expect(showHidden.value).toBe(false)
    })

    it('showHidden=true reveals archived tasks in the default (no-search) view', () => {
      const hiddenTasks = ref(makeHiddenTasks())
      const { filteredTasks, showHidden } = useTaskFilters(hiddenTasks)
      expect(filteredTasks.value.map((t) => t.id)).not.toContain(102)
      showHidden.value = true
      expect(filteredTasks.value.map((t) => t.id)).toContain(102)
    })

    it('hiddenCount reflects the number of archived (hidden) tasks', () => {
      const hiddenTasks = ref(makeHiddenTasks())
      const { hiddenCount } = useTaskFilters(hiddenTasks)
      expect(hiddenCount.value).toBe(1)
    })
  })
})
