import { ref, computed } from 'vue'

const TASK_STATUS_OPTIONS = [
  { title: 'Pending', value: 'pending' },
  { title: 'In Progress', value: 'in_progress' },
  { title: 'On hold', value: 'on_hold' },
  { title: 'Completed', value: 'completed' },
  { title: 'Blocked', value: 'blocked' },
  { title: 'Cancelled', value: 'cancelled' },
]

export const ARCHIVED_FILTER = '__archived'

export function useTaskFilters(tasks) {
  const search = ref('')
  const statusFilter = ref(null)
  const priorityFilter = ref(null)
  const showHidden = ref(false)

  const hiddenCount = computed(() => (tasks.value || []).filter((t) => t.hidden).length)

  const statusSelectOptions = computed(() => TASK_STATUS_OPTIONS.slice())

  const statusFilterOptions = computed(() => [
    ...TASK_STATUS_OPTIONS,
    { title: `Archived (${hiddenCount.value})`, value: ARCHIVED_FILTER },
  ])
  const archivedView = computed(() => statusFilter.value === ARCHIVED_FILTER)

  const filteredTasks = computed(() => {
    let list = tasks.value

    if (search.value) {
      const term = search.value.toLowerCase()
      list = list.filter(
        (t) =>
          t.title?.toLowerCase().includes(term) ||
          t.description?.toLowerCase().includes(term) ||
          t.taxonomy_alias?.toLowerCase().includes(term),
      )
    }

    if (archivedView.value) {
      list = list.filter((t) => t.hidden)
    } else if (statusFilter.value) {
      list = list.filter((t) => t.status === statusFilter.value)
    }

    if (priorityFilter.value) {
      list = list.filter((t) => t.priority === priorityFilter.value)
    }

    if (!search.value && !showHidden.value && !archivedView.value) {
      list = list.filter((t) => !t.hidden)
    }

    return list
  })

  function clearFilters() {
    search.value = ''
    statusFilter.value = null
    priorityFilter.value = null
  }

  return {
    search,
    statusFilter,
    priorityFilter,
    showHidden,
    hiddenCount,
    statusSelectOptions,
    statusFilterOptions,
    archivedView,
    filteredTasks,
    clearFilters,
  }
}
