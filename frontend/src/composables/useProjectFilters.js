import { ref, computed, watch } from 'vue'

const STATUS_STORAGE_KEY = 'giljo.projects.selectedStatuses'

export const API_MAX_PAGE_SIZE = 200

export const ARCHIVED_STATUS = '__archived'

function loadPersistedStatuses() {
  try {
    const raw = localStorage.getItem(STATUS_STORAGE_KEY)
    if (raw === null) return null
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === 'string') : null
  } catch {
    return null
  }
}

export function useProjectFilters({
  activeProduct,
  projectStatuses = ref([]),
  hiddenProjects = ref([]),
  showHidden = ref(false),
}) {
  const searchQuery = ref('')
  const currentPage = ref(1)
  const itemsPerPage = ref(10)
  const sortBy = ref([{ key: 'created_at', order: 'desc' }])

  const _selectableStatuses = computed(() =>
    (projectStatuses.value || []).filter((s) => s.value !== 'deleted'),
  )

  const statusSelectOptions = computed(() => [
    ..._selectableStatuses.value.map((s) => ({ title: s.label, value: s.value })),
    { title: `Archived (${hiddenCount.value})`, value: ARCHIVED_STATUS },
  ])

  const allStatusValues = computed(() => _selectableStatuses.value.map((s) => s.value))

  const persisted = loadPersistedStatuses()
  const selectedStatuses = ref(persisted ?? [])
  let defaulted = persisted !== null

  watch(
    allStatusValues,
    (vals) => {
      if (!defaulted && vals.length) {
        selectedStatuses.value = [...vals]
        defaulted = true
      }
    },
    { immediate: true },
  )

  watch(
    selectedStatuses,
    (vals) => {
      try {
        localStorage.setItem(STATUS_STORAGE_KEY, JSON.stringify(vals))
      } catch {
        /* localStorage unavailable (private mode / quota) — non-fatal */
      }
    },
    { deep: true },
  )

  const hiddenCount = computed(() => {
    if (!activeProduct.value) return 0
    return (hiddenProjects.value || []).filter(
      (p) => p.product_id === activeProduct.value.id && !p.deleted_at,
    ).length
  })

  const archivedSelected = computed(() => selectedStatuses.value.includes(ARCHIVED_STATUS))

  function buildServerParams() {
    const requested = itemsPerPage.value
    const limit = requested > 0 ? Math.min(requested, API_MAX_PAGE_SIZE) : API_MAX_PAGE_SIZE
    const params = {
      limit,
      offset: Math.max(0, (currentPage.value - 1) * limit),
    }
    const sb = sortBy.value && sortBy.value[0]
    if (sb && sb.key) {
      params.sort = sb.key
      params.sortDir = sb.order || 'asc'
    }
    const q = (searchQuery.value || '').trim()
    if (q) {
      params.search = q
      params.includeHidden = true
    } else {
      params.statuses = selectedStatuses.value.filter((v) => v !== ARCHIVED_STATUS)
      if (archivedSelected.value && params.statuses.length === 0) {
        delete params.statuses
        params.hiddenOnly = true
        params.includeCompleted = true
      }
    }
    if (showHidden.value || archivedSelected.value) {
      params.includeHidden = true
    }
    return params
  }

  return {
    searchQuery,
    selectedStatuses,
    showHidden,
    currentPage,
    itemsPerPage,
    sortBy,
    statusSelectOptions,
    hiddenCount,
    archivedSelected,
    buildServerParams,
  }
}
