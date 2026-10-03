import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import debounce from 'lodash-es/debounce'
import { api } from '@/services/api'
import { useProductStore } from '@/stores/products'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { immutableMapSet } from './immutableHelpers'

export const useProjectStore = defineStore('projects', () => {
  const projects = ref([])
  const deletedProjects = ref([])
  const hiddenProjects = ref([])
  const projectsTotal = ref(0)
  const activeProjectsMeta = ref([])
  const unreviewedProjectsMeta = ref([])
  const loading = ref(false)
  const error = ref(null)

  let _lastListOpts = {}

  const byId = ref(new Map())
  const entitiesById = computed(() => Array.from(byId.value.values()))

  let fetchSeq = 0
  let appliedSeq = 0

  const activeProjects = computed(() => projects.value.filter((p) => p.status === 'active'))

  const projectById = computed(
    () => (id) => entitiesById.value.find((p) => p.id === id) || projects.value.find((p) => p.id === id),
  )

  function _upsertEntity(data) {
    if (!data?.id) return data
    byId.value = immutableMapSet(byId.value, data.id, data)
    const index = projects.value.findIndex((p) => p.id === data.id)
    if (index !== -1) projects.value[index] = data
    useProjectStateStore().setProject(data)
    return data
  }

  function buildListParams({
    statusFilter = null,
    statuses = null,
    search = null,
    includeCompleted = false,
    includeHidden = false,
    hiddenOnly = false,
    sort = null,
    sortDir = null,
    limit = null,
    offset = null,
  }) {
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
      params.include_completed = true
    }
    if (includeHidden) {
      params.include_hidden = true
    }
    if (hiddenOnly) {
      params.hidden_only = true
    }
    if (sort) {
      params.sort = sort
      if (sortDir) params.sort_dir = sortDir
    }
    if (limit != null) {
      params.limit = limit
      params.offset = offset ?? 0
    }
    return params
  }

  async function fetchAllMatchingProjects(opts = {}, { pageSize = 200, max = 5000 } = {}) {
    const { statuses = null, search = null, includeCompleted = false } = opts
    if (Array.isArray(statuses) && statuses.length === 0 && !search && !includeCompleted) return []
    const rows = []
    for (let offset = 0; offset < max; offset += pageSize) {
      const params = buildListParams({ ...opts, limit: pageSize, offset })
      const response = await api.projects.list(params)
      const page = response.data || []
      rows.push(...page)
      const totalHeader = response.headers?.['x-total-count']
      const total = totalHeader != null && totalHeader !== '' ? Number(totalHeader) : null
      if (page.length < pageSize || (total != null && rows.length >= total)) break
    }
    return rows.slice(0, max)
  }

  async function fetchProjects(opts = {}) {
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
      hiddenOnly = false,
    } = opts
    if (limit != null || Array.isArray(statuses) || search) {
      _lastListOpts = { ...opts }
    }
    const seq = ++fetchSeq
    loading.value = true
    error.value = null
    try {
      if (Array.isArray(statuses) && statuses.length === 0 && !search && !includeCompleted) {
        appliedSeq = seq
        projects.value = []
        projectsTotal.value = 0
        return
      }
      const params = buildListParams({
        statusFilter,
        statuses,
        search,
        includeCompleted,
        includeHidden,
        hiddenOnly,
        sort,
        sortDir,
        limit,
        offset,
      })
      const response = await api.projects.list(params)
      if (seq <= appliedSeq) return
      appliedSeq = seq
      projects.value = response.data
      const totalHeader = response.headers?.['x-total-count']
      projectsTotal.value =
        totalHeader != null && totalHeader !== '' ? Number(totalHeader) : response.data.length
    } catch (err) {
      if (seq !== fetchSeq) return
      error.value = err.message
      console.error('Failed to fetch projects:', err)
    } finally {
      if (seq === fetchSeq) loading.value = false
    }
  }

  async function refreshList() {
    return fetchProjects(_lastListOpts)
  }

  function clearListQuery() {
    _lastListOpts = {}
  }

  const debouncedRefreshList = debounce(() => {
    refreshList()
  }, 400)

  async function fetchActiveProject({ allProducts = false } = {}) {
    try {
      const productStore = useProductStore()
      const response = await api.projects.getActive(allProducts ? null : productStore.effectiveProductId, true)
      const list = response.data || []
      activeProjectsMeta.value = list.filter((project) => !project.review_pending)
      unreviewedProjectsMeta.value = list.filter((project) => project.review_pending)
    } catch (err) {
      activeProjectsMeta.value = []
      unreviewedProjectsMeta.value = []
      console.error('Failed to fetch active project:', err)
    }
  }

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

      _upsertEntity(response.data)

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch project:', err)
    } finally {
      loading.value = false
    }
  }

  async function _mutate(label, call) {
    loading.value = true
    error.value = null
    try {
      return await call()
    } catch (err) {
      error.value = err.message
      console.error(`Failed to ${label}:`, err)
      throw err
    } finally {
      loading.value = false
    }
  }

  function _mutateAndUpsert(label, apiCall) {
    return _mutate(label, async () => {
      const response = await apiCall()
      _upsertEntity(response.data)
      return response.data
    })
  }

  function createProject(projectData) {
    return _mutate('create project', async () => {
      const response = await api.projects.create(projectData)
      await fetchProjects()
      return response.data
    })
  }

  function updateProject(id, updates) {
    return _mutateAndUpsert('update project', () => api.projects.update(id, updates))
  }

  function deleteProject(id) {
    return _mutate('delete project', async () => {
      await api.projects.delete(id)
      projects.value = projects.value.filter((p) => p.id !== id)
      await fetchDeletedProjects()
    })
  }

  async function activateProject(id) {
    loading.value = true
    error.value = null
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
      fetchProjects(_lastListOpts).catch((err) => {
        console.error('Failed to reconcile projects after activate:', err)
      })
      fetchActiveProject()
      return response.data
    } catch (err) {
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
      fetchProjects(_lastListOpts).catch((err) => {
        console.error('Failed to reconcile projects after deactivate:', err)
      })
      fetchActiveProject()
    } catch (err) {
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

  function completeProject(id) {
    return _mutateAndUpsert('complete project', () => api.projects.complete(id))
  }

  function cancelProject(id) {
    return _mutateAndUpsert('cancel project', () => api.projects.cancel(id))
  }

  async function fetchSuccessorCandidates(excludeProjectId) {
    const productStore = useProductStore()
    const params = {
      statuses: ['active', 'completed', 'inactive'],
      include_completed: true,
    }
    if (productStore.currentProductId) {
      params.product_id = productStore.currentProductId
    }
    const response = await api.projects.list(params)
    return (response.data || []).filter((p) => p.id !== excludeProjectId)
  }

  function supersedeProject(id, successorProjectId) {
    return _mutateAndUpsert('supersede project', () =>
      api.projects.update(id, { status: 'superseded', successor_project_id: successorProjectId }),
    )
  }

  function restoreProject(id) {
    return _mutate('restore project', async () => {
      const response = await api.projects.restore(id)
      deletedProjects.value = deletedProjects.value.filter((p) => p.id !== id)
      projects.value.push(response.data)
      _upsertEntity(response.data)
      return response.data
    })
  }

  function purgeDeletedProject(id) {
    return _mutate('purge deleted project', async () => {
      await api.projects.purgeDeleted(id)
      deletedProjects.value = deletedProjects.value.filter((p) => p.id !== id)
      await fetchDeletedProjects()
    })
  }

  function purgeAllDeletedProjects() {
    return _mutate('purge all deleted projects', async () => {
      const productStore = useProductStore()
      const params = {}
      if (productStore.currentProductId) {
        params.product_id = productStore.currentProductId
      }
      await api.projects.purgeAllDeleted(params)
      deletedProjects.value = []
      await fetchDeletedProjects()
    })
  }

  function restoreCompletedProject(id) {
    return _mutateAndUpsert('restore completed project', () => api.projects.restoreCompleted(id))
  }


  const LIST_EXCLUDED_STATUSES = new Set(['deleted', 'superseded'])

  async function handleRealtimeUpdate(data) {
    const { project_id, update_type } = data
    if (!project_id) return

    if (update_type === 'created') {
      refreshList()
      return
    }

    const updated = await fetchProject(project_id)

    if (updated && LIST_EXCLUDED_STATUSES.has(updated.status)) {
      projects.value = projects.value.filter((p) => p.id !== project_id)
    }

    if (update_type === 'status_changed') {
      fetchActiveProject()
    }
  }

  return {
    projects,
    deletedProjects,
    hiddenProjects,
    projectsTotal,
    activeProjectsMeta,
    unreviewedProjectsMeta,
    loading,
    error,

    activeProjects,
    projectById,

    fetchProjects,
    refreshList,
    debouncedRefreshList,
    clearListQuery,
    fetchActiveProject,
    fetchHiddenProjects,
    fetchDeletedProjects,
    fetchProject,
    createProject,
    updateProject,
    deleteProject,
    fetchAllMatchingProjects,
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
