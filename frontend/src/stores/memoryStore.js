import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/services/api'
import { immutableMapSet } from './immutableHelpers'

export const useMemoryStore = defineStore('memory', () => {
  const byId = ref(new Map())
  const loading = ref(false)
  const error = ref(null)
  const loadedProductId = ref(null)

  const searchText = ref('')
  const selectedTags = ref([])
  const selectedProjectId = ref(null)
  const sortMode = ref('date_desc')
  const groupByProject = ref(false)
  const serverSearch = ref(false)
  const inFlightSearch = ref(null)

  let loadSeq = 0

  const entries = computed(() => Array.from(byId.value.values()))

  const availableTags = computed(() => {
    const set = new Set()
    for (const e of entries.value) {
      for (const t of e.tags || []) set.add(t)
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  })

  const availableProjects = computed(() => {
    const map = new Map()
    for (const e of entries.value) {
      if (e.project_id && !map.has(e.project_id)) {
        map.set(e.project_id, { id: e.project_id, name: e.project_name || 'Untitled project' })
      }
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name))
  })

  function _matchesSearch(entry, needle) {
    if (!needle) return true
    const haystack = [
      entry.summary || '',
      entry.project_name || '',
      ...(entry.key_outcomes || []),
      ...(entry.decisions_made || []),
      ...(entry.tags || []),
    ]
      .join('\n')
      .toLowerCase()
    return haystack.includes(needle)
  }

  function _matchesTags(entry, tags) {
    if (!tags.length) return true
    const entryTags = entry.tags || []
    return tags.some((t) => entryTags.includes(t))
  }

  function _sortComparator(mode) {
    switch (mode) {
      case 'date_asc':
        return (a, b) => _ts(a) - _ts(b)
      case 'sequence_desc':
        return (a, b) => (b.sequence ?? 0) - (a.sequence ?? 0)
      case 'sequence_asc':
        return (a, b) => (a.sequence ?? 0) - (b.sequence ?? 0)
      case 'date_desc':
      default:
        return (a, b) => _ts(b) - _ts(a)
    }
  }

  function _ts(entry) {
    const t = entry.timestamp ? Date.parse(entry.timestamp) : NaN
    return Number.isNaN(t) ? 0 : t
  }

  const filteredEntries = computed(() => {
    const needle = searchText.value.trim().toLowerCase()
    const tags = selectedTags.value
    const projectId = selectedProjectId.value
    const result = entries.value.filter(
      (e) =>
        (serverSearch.value || _matchesSearch(e, needle)) &&
        _matchesTags(e, tags) &&
        (!projectId || e.project_id === projectId),
    )
    result.sort(_sortComparator(sortMode.value))
    return result
  })

  const groupedByProjectEntries = computed(() => {
    const groups = new Map()
    for (const e of filteredEntries.value) {
      const key = e.project_id || '__none__'
      if (!groups.has(key)) {
        groups.set(key, {
          project_id: e.project_id || null,
          project_name: e.project_name || 'Unassigned',
          entries: [],
        })
      }
      groups.get(key).entries.push(e)
    }
    return Array.from(groups.values())
  })

  function _upsertEntry(entry) {
    if (!entry?.id) return entry
    byId.value = immutableMapSet(byId.value, entry.id, entry)
    return entry
  }

  async function fetchMemoryEntries(productId, { limit = 100 } = {}) {
    if (!productId) return
    const seq = ++loadSeq
    loading.value = true
    error.value = null
    try {
      const response = await api.products.getMemoryEntries(productId, { limit })
      if (seq !== loadSeq) return
      const list = response?.data?.entries || []
      byId.value = new Map()
      for (const entry of list) _upsertEntry(entry)
      loadedProductId.value = productId
      serverSearch.value = false
    } catch (err) {
      if (seq !== loadSeq) return
      error.value = err.message
      console.error('Failed to fetch memory entries:', err)
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }

  function searchMemoryEntries(productId, term, { limit = 100 } = {}) {
    const promise = _runSearch(productId, term, { limit })
    inFlightSearch.value = promise
    const settled = () => {
      if (inFlightSearch.value === promise) inFlightSearch.value = null
    }
    promise.then(settled, settled)
    return promise
  }

  async function _runSearch(productId, term, { limit = 100 } = {}) {
    if (!productId) return
    const trimmed = (term || '').trim()
    if (!trimmed) {
      await fetchMemoryEntries(productId, { limit })
      return
    }
    const seq = ++loadSeq
    loading.value = true
    error.value = null
    try {
      const response = await api.products.getMemoryEntries(productId, { limit, search: trimmed })
      if (seq !== loadSeq) return
      const list = response?.data?.entries || []
      byId.value = new Map()
      for (const entry of list) _upsertEntry(entry)
      loadedProductId.value = productId
      serverSearch.value = true
    } catch (err) {
      if (seq !== loadSeq) return
      error.value = err.message
      console.error('Failed to search memory entries:', err)
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }

  function handleMemoryEntryWritten(productId, entry) {
    if (!productId || !entry?.id || loadedProductId.value !== productId) return
    _upsertEntry(entry)
  }

  function clearFilters() {
    searchText.value = ''
    selectedTags.value = []
    selectedProjectId.value = null
    serverSearch.value = false
  }

  return {
    byId,
    loading,
    error,
    loadedProductId,
    searchText,
    selectedTags,
    selectedProjectId,
    sortMode,
    groupByProject,
    serverSearch,
    inFlightSearch,
    entries,
    availableTags,
    availableProjects,
    filteredEntries,
    groupedByProjectEntries,
    fetchMemoryEntries,
    searchMemoryEntries,
    handleMemoryEntryWritten,
    clearFilters,
    _upsertEntry,
  }
})
