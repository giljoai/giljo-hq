import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/services/api'
import { immutableMapSet } from './immutableHelpers'

/**
 * FE-5042 — 360 Memory Browser store.
 *
 * Follows the FE-3007 normalized pattern: `byId` is the single owner of the
 * memory ENTITY keyed by id, and `_upsertEntry` is the ONE write path that
 * feeds it (via immutableMapSet — no ad-hoc cache, no per-field whitelist).
 *
 * Tag / project / sort are CLIENT-SIDE computeds over the loaded set. Free-text
 * search is GRACEFUL (BE-6082): for a small loaded set the client-side
 * `_matchesSearch` substring filter is sub-millisecond, so browsing ships with
 * zero backend; when a search term is present `searchMemoryEntries()` calls the
 * server `?search=` tsvector path so results scale past the 100-entry read cap.
 * When server search is active (`serverSearch`), `filteredEntries` trusts the
 * server's text match (it does NOT re-apply the client substring filter, which
 * would hide stemmed/relevance matches) but still applies tag/project/sort.
 *
 * Edition scope: Both (360 memory is core; CE users have memory entries too).
 */
export const useMemoryStore = defineStore('memory', () => {
  // ── Entity state (FE-3007 normalized owner) ──────────────────────────────
  const byId = ref(new Map())
  const loading = ref(false)
  const error = ref(null)
  const loadedProductId = ref(null)

  // ── Filter / sort UI state (drives the client-side computeds) ─────────────
  const searchText = ref('')
  const selectedTags = ref([]) // AND-less: an entry matches if it carries ANY selected tag
  const selectedProjectId = ref(null)
  const sortMode = ref('date_desc') // date_desc | date_asc | sequence_desc | sequence_asc
  const groupByProject = ref(false)
  // True while the loaded set is the result of a server-side ?search= query, so
  // filteredEntries skips the client-side substring match (BE-6082).
  const serverSearch = ref(false)
  // FE-9338: the in-flight search promise. The view fires searchMemoryEntries()
  // fire-and-forget from a 250ms debounce, so nothing outside the store can tell
  // when the result has landed. Exposing the promise lets callers await THAT
  // search settling instead of guessing at it. Reset to null when the search it
  // points at settles.
  const inFlightSearch = ref(null)

  // IMP-9342: load sequencing token. fetchMemoryEntries and _runSearch both
  // REPLACE the loaded set wholesale, so they race each other as well as
  // themselves — without this the last response to arrive won, not the last one
  // requested. Every load claims the next token before awaiting and applies its
  // result only if it still holds it; a superseded response is dropped whole
  // (entities, serverSearch, loadedProductId, error and loading alike).
  // Store-instance scoped, not module scope, so it cannot leak between tests.
  let loadSeq = 0

  // ── Getters ───────────────────────────────────────────────────────────────
  const entries = computed(() => Array.from(byId.value.values()))

  /** Unique tags across all loaded entries, sorted — feeds the tag filter. */
  const availableTags = computed(() => {
    const set = new Set()
    for (const e of entries.value) {
      for (const t of e.tags || []) set.add(t)
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  })

  /** Unique {id, name} projects across loaded entries — feeds the project filter. */
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

  /**
   * The client-side search/filter/sort result the view binds to. A single
   * pass: free-text across summary/outcomes/decisions/project/tags, then tag
   * filter, then project filter, then sort.
   */
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

  /** filteredEntries grouped into project sections (preserves the sort order). */
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

  // ── Single write path ─────────────────────────────────────────────────────
  function _upsertEntry(entry) {
    if (!entry?.id) return entry
    byId.value = immutableMapSet(byId.value, entry.id, entry)
    return entry
  }

  // ── Actions ────────────────────────────────────────────────────────────────
  /**
   * Fetch 360 memory entries for a product and load them through the single
   * write path. Reuses the EXISTING read endpoint (api.products.getMemoryEntries
   * → GET /products/{id}/memory-entries). The endpoint caps `limit` at 100; we
   * request the max and search client-side over the loaded set.
   */
  async function fetchMemoryEntries(productId, { limit = 100 } = {}) {
    if (!productId) return
    const seq = ++loadSeq
    loading.value = true
    error.value = null
    try {
      const response = await api.products.getMemoryEntries(productId, { limit })
      if (seq !== loadSeq) return // superseded mid-flight — drop this response
      const list = response?.data?.entries || []
      // Replace the set for this product (fresh load), then upsert each entry
      // through the single write path so byId is the sole owner.
      byId.value = new Map()
      for (const entry of list) _upsertEntry(entry)
      loadedProductId.value = productId
      serverSearch.value = false
    } catch (err) {
      if (seq !== loadSeq) return
      error.value = err.message
      console.error('Failed to fetch memory entries:', err)
    } finally {
      // Only the newest load owns the flag; a stale one must not report the
      // still-running newer request as finished.
      if (seq === loadSeq) loading.value = false
    }
  }

  /**
   * BE-6082 — graceful server-side full-text search.
   *
   * When `term` is blank, falls back to the client-side path: it loads the full
   * set via fetchMemoryEntries() and lets the client-side computeds filter it
   * (no regression for small datasets). When `term` is present, it hits the
   * server `?search=` tsvector path and loads the matched + relevance-ranked set
   * through the single write path, marking `serverSearch` so filteredEntries
   * trusts the server's text match.
   */
  function searchMemoryEntries(productId, term, { limit = 100 } = {}) {
    const promise = _runSearch(productId, term, { limit })
    inFlightSearch.value = promise
    // Release the ref once this search settles, so a settled promise is never
    // left parked in public store state. Identity-checked: a slow older search
    // settling late must not clear a newer search that is still in flight.
    // then(fn, fn) rather than finally() — finally() would derive a REJECTED
    // promise nobody handles when the search rejects.
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
      // Client-side fallback: reload the full set (clears serverSearch). It
      // claims its own token inside fetchMemoryEntries, so it sequences against
      // the server-search path below too — clearing the box then typing again
      // must not let the full reload land on top of the newer search.
      await fetchMemoryEntries(productId, { limit })
      return
    }
    const seq = ++loadSeq
    loading.value = true
    error.value = null
    try {
      const response = await api.products.getMemoryEntries(productId, { limit, search: trimmed })
      if (seq !== loadSeq) return // superseded mid-flight — drop this response
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

  function clearFilters() {
    searchText.value = ''
    selectedTags.value = []
    selectedProjectId.value = null
    serverSearch.value = false
  }

  return {
    // State
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
    // Getters
    entries,
    availableTags,
    availableProjects,
    filteredEntries,
    groupedByProjectEntries,
    // Actions
    fetchMemoryEntries,
    searchMemoryEntries,
    clearFilters,
    // Exposed for tests / direct upsert (single write path)
    _upsertEntry,
  }
})
