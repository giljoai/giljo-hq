import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/services/api'
import { useProductStore } from '@/stores/products'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { immutableMapSet } from './immutableHelpers'

export const useProjectStore = defineStore('projects', () => {
  // State
  const projects = ref([])
  const deletedProjects = ref([])
  // BE-6078: hidden rows are filtered out of the default list server-side and
  // fetched separately (the "Show hidden" view). Kept in their own array so the
  // main list payload stays lean and the hidden count is available for the
  // conditional "Show hidden (N)" affordance.
  const hiddenProjects = ref([])
  // BE-6076: server-side pagination. `projects` now holds the current SERVER
  // PAGE (not the full set); `projectsTotal` is the filtered total carried on
  // the X-Total-Count response header, bound to the table's :items-length.
  const projectsTotal = ref(0)
  // BE-6076: with pagination the active project may be off the current page, so
  // `hasActiveProject` can no longer be derived from `projects`. Track it from a
  // dedicated /projects/active read instead (single-active-project invariant).
  const activeProjectMeta = ref(null)
  const loading = ref(false)
  const error = ref(null)

  // BE-6076: remember the last server-mode list query so the detached
  // post-mutation reconciles (activate/deactivate) re-fetch the SAME page+filters
  // instead of clobbering the paginated view with the bare default set.
  let _lastListOpts = {}

  // FE-3007a: byId is the single normalized owner of the FULL project entity,
  // keyed by id. The `projects` array holds the trimmed list rows for tables;
  // detail views read the COMPLETE entity (mission/description/taxonomy/...)
  // from here. One write path (_upsertEntity) feeds both, so there is no
  // per-field whitelist to drift between caches.
  const byId = ref(new Map())
  const entitiesById = computed(() => Array.from(byId.value.values()))

  // Monotonic request sequence for fetchProjects. The projects list is fetched
  // from two racing call sites (the onMounted default fetch and the status-filter
  // re-fetch with include_completed=true). On a cold load the slower default
  // response could land AFTER the newer full-set response and blindly overwrite
  // it — wiping completed/cancelled rows back to active+inactive. We stamp every
  // call with a seq and only let the latest dispatched call apply its response.
  let fetchSeq = 0

  // Getters
  const activeProjects = computed(() => projects.value.filter((p) => p.status === 'active'))

  // Product/Project State Fix: Track THE active project (singular) for nav links
  const activeProject = computed(() => {
    return projects.value.find((p) => p.status === 'active' && !p.deleted_at) || null
  })

  // FE-3007a: prefer the complete entity in byId; fall back to the trimmed
  // list row when an entity has only been seen in a list fetch.
  const projectById = computed(
    () => (id) => entitiesById.value.find((p) => p.id === id) || projects.value.find((p) => p.id === id),
  )

  /**
   * FE-3007a: the ONE write path for project entities. Stores the complete
   * entity in byId and keeps the matching list row in sync when present.
   * Does NOT inject detail-only entities into the list array (so opening a
   * completed/archived project's page never pollutes the active list view).
   */
  function _upsertEntity(data) {
    if (!data?.id) return data
    byId.value = immutableMapSet(byId.value, data.id, data)
    const index = projects.value.findIndex((p) => p.id === data.id)
    if (index !== -1) projects.value[index] = data
    // FE-9122: derived-state store hydrates from the same single write path.
    useProjectStateStore().setProject(data)
    return data
  }

  // Actions
  /**
   * Fetch the project list from the server.
   *
   * Backward-compatible: called with no args (or only includeCompleted/
   * statusFilter) it behaves exactly as before — a bare, unpaginated list — so
   * every existing caller (activate/deactivate reconcile, realtime refresh,
   * create) is unaffected. BE-6076 adds opt-in server-side pagination/search/
   * sort/multi-status when those keys are passed (the Projects page).
   *
   * @param {Object} [opts]
   * @param {boolean} [opts.includeCompleted=false] - include_completed=true →
   *   finished/archived rows (completed/cancelled/terminated) are returned.
   * @param {string|null} [opts.statusFilter=null] - explicit single status_filter.
   * @param {string[]|null} [opts.statuses=null] - BE-6076 multi-status filter
   *   (the Status multi-select). An EMPTY array means "no statuses selected" →
   *   the page is empty (short-circuited; no request) rather than the default-all.
   * @param {string|null} [opts.search=null] - BE-6076 substring search.
   * @param {string|null} [opts.sort=null] / [opts.sortDir=null] - BE-6076 sort.
   * @param {number|null} [opts.limit=null] / [opts.offset=null] - BE-6076 page.
   * @param {boolean} [opts.includeHidden=false] - BE-6076 "Show hidden" (both).
   */
  async function fetchProjects(opts = {}) {
    // Defensive anti-clobber: a "bare" refresh (no list-defining params) — the
    // products-store post-activate refresh, a WS `project:created` event, a
    // reconnect resync, a post-create reload — refetches the active-lifecycle
    // DEFAULT (inactive+active). Landing with a newer fetchSeq than the Projects
    // page's filter fetch, it legitimately wins and overwrites the filtered view:
    // the "select Completed → 29 rows flash → revert to the 65 inactive default"
    // bug seen live. While a server-mode query is active (the Projects page),
    // replay THAT query instead of the bare default. `_lastListOpts` is cleared
    // on Projects-page unmount (clearListQuery) so other views (e.g. WelcomeView)
    // that intentionally want the default list still get it.
    const _isBareRefresh =
      opts.statusFilter == null &&
      opts.statuses == null &&
      !opts.search &&
      !opts.includeCompleted &&
      opts.limit == null
    const _serverModeActive =
      _lastListOpts && (_lastListOpts.limit != null || Array.isArray(_lastListOpts.statuses))
    if (_isBareRefresh && _serverModeActive) {
      opts = { ..._lastListOpts }
    }
    const {
      includeCompleted = false,
      statusFilter = null,
      statuses = null,
      search = null,
      sort = null,
      sortDir = null,
      limit = null,
      offset = null,
      includeHidden = false,
    } = opts
    // Remember server-mode queries so detached reconciles re-fetch this page.
    if (limit != null || Array.isArray(statuses) || search) {
      _lastListOpts = { ...opts }
    }
    const seq = ++fetchSeq
    loading.value = true
    error.value = null
    try {
      // Empty multi-select (no statuses, not searching) → empty page, no request.
      if (Array.isArray(statuses) && statuses.length === 0 && !search && !includeCompleted) {
        projects.value = []
        projectsTotal.value = 0
        return
      }
      const productStore = useProductStore()
      const params = {}
      if (productStore.currentProductId) {
        params.product_id = productStore.currentProductId
      }
      if (statusFilter) {
        params.status_filter = statusFilter
      } else if (Array.isArray(statuses) && statuses.length > 0) {
        params.statuses = statuses
      } else if (includeCompleted) {
        params.include_completed = true
      }
      if (search) {
        params.search = search
        // Nuclear search: match across all lifecycle statuses (ignore the
        // multi-select), mirroring the prior client-side behavior.
        params.include_completed = true
      }
      if (includeHidden) {
        params.include_hidden = true
      }
      if (sort) {
        params.sort = sort
        if (sortDir) params.sort_dir = sortDir
      }
      if (limit != null) {
        params.limit = limit
        params.offset = offset ?? 0
      }
      const response = await api.projects.list(params)
      // Drop a stale response: a newer fetchProjects was dispatched while this
      // request was in flight, so applying this older payload would clobber it.
      if (seq !== fetchSeq) return
      projects.value = response.data
      // X-Total-Count is the filtered total when paginating; fall back to the
      // returned row count on the legacy (unpaginated) path.
      const totalHeader = response.headers?.['x-total-count']
      projectsTotal.value =
        totalHeader != null && totalHeader !== '' ? Number(totalHeader) : response.data.length
    } catch (err) {
      if (seq !== fetchSeq) return
      error.value = err.message
      console.error('Failed to fetch projects:', err)
    } finally {
      // Only the latest dispatched call owns the loading flag.
      if (seq === fetchSeq) loading.value = false
    }
  }

  /**
   * Re-fetch the CURRENT server-mode list query (filters + sort + page), not the
   * bare active-lifecycle default. Realtime + reconnect refreshers MUST use this:
   * a bare `fetchProjects()` refetches the default (inactive+active) set and, by
   * landing with a newer fetchSeq than the user's filter fetch, legitimately wins
   * and CLOBBERS the active filter — the "select Completed → flashes → reverts to
   * the inactive list" bug. Replaying `_lastListOpts` preserves what the user is
   * actually looking at. Falls back to a bare fetch before any server-mode query
   * has run (`_lastListOpts` is `{}`), which is correct for the default list.
   */
  async function refreshList() {
    return fetchProjects(_lastListOpts)
  }

  /**
   * Forget the remembered server-mode query. The Projects page calls this on
   * unmount so the anti-clobber guard in fetchProjects() deactivates and other
   * views (WelcomeView etc.) that call a bare fetchProjects() get the true
   * default list rather than this page's last filter.
   */
  function clearListQuery() {
    _lastListOpts = {}
  }

  /**
   * BE-6076: read THE active project (single-active-project invariant) so the
   * Projects page can disable "Activate" even when the active row is off the
   * current paginated page. A 404/None response clears it.
   */
  async function fetchActiveProject() {
    try {
      const response = await api.projects.getActive()
      activeProjectMeta.value = response.data || null
    } catch (err) {
      // No active project (or transient error) → treat as none; non-fatal.
      activeProjectMeta.value = null
      console.error('Failed to fetch active project:', err)
    }
  }

  /**
   * BE-6078: fetch the HIDDEN projects across all lifecycle statuses (the
   * "Show hidden" view). Uses the server-side hidden offload — hidden_only=true
   * returns only hidden rows, include_completed=true so finished hidden rows are
   * included too. Listing is a pure read; it never re-tags (unhide stays the
   * per-row hamburger action).
   */
  async function fetchHiddenProjects() {
    try {
      const productStore = useProductStore()
      const params = { include_completed: true, hidden_only: true }
      if (productStore.currentProductId) {
        params.product_id = productStore.currentProductId
      }
      const response = await api.projects.list(params)
      hiddenProjects.value = response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch hidden projects:', err)
    }
  }

  async function fetchDeletedProjects() {
    loading.value = true
    error.value = null
    try {
      const productStore = useProductStore()
      const params = {}
      if (productStore.currentProductId) {
        params.product_id = productStore.currentProductId
      }
      const response = await api.projects.fetchDeleted(params)
      deletedProjects.value = response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch deleted projects:', err)
    } finally {
      loading.value = false
    }
  }

  async function fetchProject(id) {
    loading.value = true
    error.value = null
    try {
      const response = await api.projects.get(id)

      // FE-3007a: upsert the complete entity into byId (single write path),
      // even when the project is not in the list array — detail pages and
      // deep-links land here too (store writer COMPLETE).
      _upsertEntity(response.data)

      // IMP-1002: return the full detail so callers can guard against a
      // failed GET before opening the edit dialog (list rows carry trimmed
      // ProjectListResponse — no mission/description).
      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch project:', err)
      // Return undefined on failure; callers guard on falsy before seeding UI.
    } finally {
      loading.value = false
    }
  }

  async function createProject(projectData) {
    loading.value = true
    error.value = null
    try {
      const response = await api.projects.create(projectData)

      // CRITICAL: Refresh from backend to get actual status
      // Backend may auto-activate project (Single Active Project constraint)
      // or modify other fields. Don't trust local request data.
      await fetchProjects()

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to create project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function updateProject(id, updates) {
    loading.value = true
    error.value = null
    try {
      const response = await api.projects.update(id, updates)

      _upsertEntity(response.data)

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to update project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function deleteProject(id) {
    loading.value = true
    error.value = null
    try {
      await api.projects.delete(id)

      projects.value = projects.value.filter((p) => p.id !== id)

      // Refresh deleted projects list after deletion
      await fetchDeletedProjects()
    } catch (err) {
      error.value = err.message
      console.error('Failed to delete project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  // Handover 0062: Activate project
  async function activateProject(id) {
    loading.value = true
    error.value = null
    // Optimistic update with rollback on failure
    const index = projects.value.findIndex((p) => p.id === id)
    const previous = index !== -1 ? { ...projects.value[index] } : null
    if (index !== -1) {
      projects.value[index] = {
        ...projects.value[index],
        status: 'active',
        updated_at: new Date().toISOString(),
      }
    }
    try {
      const response = await api.projects.activate(id)
      // IMP-1002: detach the list reconcile so the caller's router.push
      // fires immediately instead of waiting for a full reload. The optimistic
      // update above already flipped the clicked row; fetchProjects still runs
      // to reconcile sibling deactivation (single-active-project constraint).
      // BE-6076: re-fetch the SAME page+filters (not the bare default) so the
      // paginated Projects view is not clobbered; refresh the active-project flag.
      fetchProjects(_lastListOpts).catch((err) => {
        console.error('Failed to reconcile projects after activate:', err)
      })
      fetchActiveProject()
      return response.data
    } catch (err) {
      // Roll back optimistic update
      if (index !== -1 && previous) {
        projects.value[index] = previous
      }
      error.value = err.message || 'Failed to activate project'
      console.error('Failed to activate project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function deactivateProject(id) {
    loading.value = true
    error.value = null
    // Optimistic update with rollback on failure
    const index = projects.value.findIndex((p) => p.id === id)
    const previous = index !== -1 ? { ...projects.value[index] } : null
    if (index !== -1) {
      projects.value[index] = {
        ...projects.value[index],
        status: 'inactive',
        updated_at: new Date().toISOString(),
      }
    }
    try {
      await api.projects.deactivate(id)
      // IMP-1002: detach the list reconcile (mirrors activateProject change).
      // BE-6076: same-page reconcile + active-project refresh (see activateProject).
      fetchProjects(_lastListOpts).catch((err) => {
        console.error('Failed to reconcile projects after deactivate:', err)
      })
      fetchActiveProject()
    } catch (err) {
      // Roll back optimistic update
      if (index !== -1 && previous) {
        projects.value[index] = previous
      }
      error.value = err.message || 'Failed to deactivate project'
      console.error('Failed to deactivate project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function completeProject(id) {
    loading.value = true
    error.value = null
    try {
      const response = await api.projects.complete(id)

      _upsertEntity(response.data)

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to complete project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function cancelProject(id) {
    loading.value = true
    error.value = null
    try {
      const response = await api.projects.cancel(id)

      _upsertEntity(response.data)

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to cancel project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * BE-9157: candidate successor projects for the Mark Superseded picker.
   * Pulls active+completed projects (a project can only be superseded BY a
   * still-relevant project, not a cancelled/terminated/deleted one), scoped to
   * the active product like every other list read, and excludes the project
   * being superseded (it can't be its own successor). FE-9485: `limit` is
   * intentionally omitted rather than paginated — GET /api/v1/projects/ caps
   * `limit` at 200 (BE-6076's deliberate page-size bound), and per that
   * endpoint's own docstring, omitting `limit` returns the full set, which is
   * what the picker needs (unlike the paginated `projects` array, which only
   * holds the current page).
   */
  async function fetchSuccessorCandidates(excludeProjectId) {
    const productStore = useProductStore()
    const params = {
      statuses: ['active', 'completed'],
      include_completed: true,
    }
    if (productStore.currentProductId) {
      params.product_id = productStore.currentProductId
    }
    const response = await api.projects.list(params)
    return (response.data || []).filter((p) => p.id !== excludeProjectId)
  }

  /**
   * BE-9157: mark a project superseded and record its successor. Backend
   * validates the successor is a real within-tenant project and not self
   * (422 on violation) — let that propagate so the picker modal can surface it.
   */
  async function supersedeProject(id, successorProjectId) {
    loading.value = true
    error.value = null
    try {
      const response = await api.projects.update(id, {
        status: 'superseded',
        successor_project_id: successorProjectId,
      })

      _upsertEntity(response.data)

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to supersede project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function restoreProject(id) {
    loading.value = true
    error.value = null
    try {
      const response = await api.projects.restore(id)

      // Remove from deleted projects list
      deletedProjects.value = deletedProjects.value.filter((p) => p.id !== id)

      // Add to active projects list
      projects.value.push(response.data)
      // FE-3007a: register the complete entity in byId too (single owner)
      _upsertEntity(response.data)

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to restore project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function purgeDeletedProject(id) {
    loading.value = true
    error.value = null
    try {
      await api.projects.purgeDeleted(id)
      deletedProjects.value = deletedProjects.value.filter((p) => p.id !== id)
      await fetchDeletedProjects()
    } catch (err) {
      error.value = err.message
      console.error('Failed to purge deleted project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function purgeAllDeletedProjects() {
    loading.value = true
    error.value = null
    try {
      const productStore = useProductStore()
      const params = {}
      if (productStore.currentProductId) {
        params.product_id = productStore.currentProductId
      }
      await api.projects.purgeAllDeleted(params)
      deletedProjects.value = []
      await fetchDeletedProjects()
    } catch (err) {
      error.value = err.message
      console.error('Failed to purge all deleted projects:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function restoreCompletedProject(id) {
    loading.value = true
    error.value = null
    try {
      const response = await api.projects.restoreCompleted(id)

      _upsertEntity(response.data)

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to restore completed project:', err)
      throw err
    } finally {
      loading.value = false
    }
  }


  // Handle real-time updates from WebSocket
  //
  // FE-3007a: full-refetch-on-event. Instead of hand-copying a name/status/
  // mission/description whitelist off the payload (which drifted out of sync
  // with the API shape and shipped two stale-state bugs), we re-pull the
  // affected entity from the API through the single write path. The payload's
  // job is now only to tell us WHICH project changed, not to carry its fields.
  function handleRealtimeUpdate(data) {
    const { project_id, update_type } = data
    if (!project_id) return

    if (update_type === 'created') {
      // Not in our cache yet — refresh the list to pick it up. Use refreshList()
      // (replays the active filter/sort/page) NOT a bare fetchProjects(), which
      // would clobber a filtered view with the active-lifecycle default.
      refreshList()
      return
    }

    // Any other lifecycle event (updated/closed/status_changed/activated/
    // deactivated/...) → refetch the complete entity. fetchProject upserts
    // byId and syncs the list row when present, so every view that reads the
    // store reflects the change with zero whitelist code.
    fetchProject(project_id)
  }

  return {
    // State
    projects,
    deletedProjects,
    hiddenProjects,
    projectsTotal,
    activeProjectMeta,
    loading,
    error,

    // Getters
    activeProjects,
    activeProject,  // Product/Project State Fix: Singular active project for nav
    projectById,

    // Actions
    fetchProjects,
    refreshList,
    clearListQuery,
    fetchActiveProject,
    fetchHiddenProjects,
    fetchDeletedProjects,
    fetchProject,
    createProject,
    updateProject,
    deleteProject,
    activateProject,
    deactivateProject,
    completeProject,
    cancelProject,
    fetchSuccessorCandidates,
    supersedeProject,
    restoreProject,
    restoreCompletedProject,
    purgeDeletedProject,
    purgeAllDeletedProjects,
    handleRealtimeUpdate,
  }
})
