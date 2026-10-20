
const seriesProductIdParam = (productId) => (productId ? { product_id: productId } : {})

export const createTaxonomyTypesApi = (apiClient) => ({
  list: () => apiClient.get('/api/v1/taxonomy-types/'),
  create: (data) => apiClient.post('/api/v1/taxonomy-types/', data),
  update: (id, data) => apiClient.put(`/api/v1/taxonomy-types/${id}`, data),
  delete: (id) => apiClient.delete(`/api/v1/taxonomy-types/${id}`),
})

export const createProjectStatusesApi = (apiClient) => ({
  list: () => apiClient.get('/api/v1/project-statuses/'),
})

export const createTaskStatusesApi = (apiClient) => ({
  list: () => apiClient.get('/api/v1/task-statuses/'),
})

export const createProjectsApi = (apiClient) => ({
  list: (params) => apiClient.get('/api/v1/projects/', { params }),
  get: (id) => apiClient.get(`/api/v1/projects/${id}`),
  review: (id) => apiClient.get(`/api/v1/projects/${id}/review`),
  getOrchestrator: (id) => apiClient.get(`/api/v1/projects/${id}/orchestrator`),
  getActive: (productId, includeUnreviewed = false) =>
    apiClient.get('/api/v1/projects/active', {
      params: {
        ...(productId ? { product_id: productId } : {}),
        ...(includeUnreviewed ? { include_unreviewed: true } : {}),
      },
    }),
  markReviewed: (id) => apiClient.post(`/api/v1/projects/${id}/reviewed`),
  create: (data) => apiClient.post('/api/v1/projects/', data),
  update: (id, data) => apiClient.patch(`/api/v1/projects/${id}`, data),
  delete: (id) => apiClient.delete(`/api/v1/projects/${id}`),
  fetchDeleted: (params) => apiClient.get('/api/v1/projects/deleted', { params }),
  getNextSeries: (typeId, productId = null) =>
    apiClient.get('/api/v1/projects/next-series', { params: { type_id: typeId, ...seriesProductIdParam(productId) } }),
  getAvailableSeries: (typeId, limit = 5, productId = null) =>
    apiClient.get('/api/v1/projects/available-series', { params: { type_id: typeId, limit, ...seriesProductIdParam(productId) } }),
  checkSeries: (typeId, seriesNumber, subseries = null, excludeProjectId = null, options = {}, productId = null) =>
    apiClient.get('/api/v1/projects/check-series', {
      params: { ...(typeId && { type_id: typeId }), series_number: seriesNumber, subseries, exclude_project_id: excludeProjectId, ...seriesProductIdParam(productId) },
      ...options,
    }),
  usedSubseries: (typeId, seriesNumber, excludeProjectId = null, options = {}, productId = null) =>
    apiClient.get('/api/v1/projects/used-subseries', {
      params: { ...(typeId && { type_id: typeId }), series_number: seriesNumber, exclude_project_id: excludeProjectId, ...seriesProductIdParam(productId) },
      ...options,
    }),
  activate: (id, force = false) => apiClient.post(`/api/v1/projects/${id}/activate`, { force }),
  deactivate: (id, reason = null) =>
    apiClient.post(`/api/v1/projects/${id}/deactivate`, { reason }),
  complete: (id) => apiClient.post(`/api/v1/projects/${id}/complete`),
  cancel: (id) => apiClient.post(`/api/v1/projects/${id}/cancel`),
  restore: (id) => apiClient.post(`/api/v1/projects/${id}/restore`),
  purgeDeleted: (id) => apiClient.delete(`/api/v1/projects/${id}/purge`),
  purgeAllDeleted: (params) => apiClient.delete('/api/v1/projects/deleted', { params }),
  restoreCompleted: (id) => apiClient.post(`/api/v1/projects/${id}/continue-working`),
  cancelStaging: (id) => apiClient.post(`/api/v1/projects/${id}/cancel-staging`),
  restage: (id) => apiClient.post(`/api/v1/projects/${id}/restage`),
  reset: (id) => apiClient.post(`/api/v1/projects/${id}/reset`),
  unstage: (id) => apiClient.post(`/api/v1/projects/${id}/unstage`),
  completeWithData: (id, data) => apiClient.post(`/api/v1/projects/${id}/complete`, data),
  archive: (id) => apiClient.post(`/api/v1/projects/${id}/archive`),
  closeoutWithoutSummary: (id, reason) =>
    apiClient.post(`/api/v1/projects/${id}/closeout-without-summary`, { reason }),
  launchImplementation: (id) =>
    apiClient.patch(`/api/agent-jobs/projects/${id}/launch-implementation`),
})

export const createTasksApi = (apiClient) => ({
  list: (params = {}) => apiClient.get('/api/v1/tasks/', { params: { limit: 500, ...params } }),
  get: (id) => apiClient.get(`/api/v1/tasks/${id}/`),
  create: (data) => apiClient.post('/api/v1/tasks/', data),
  update: (id, data) => apiClient.put(`/api/v1/tasks/${id}/`, data),
  delete: (id) => apiClient.delete(`/api/v1/tasks/${id}/`),
  changeStatus: (id, status) => apiClient.patch(`/api/v1/tasks/${id}/status/`, { status }),
  convertToProject: (id) => apiClient.post(`/api/v1/tasks/${id}/convert`, {}),
  getDeleted: (params) => apiClient.get('/api/v1/tasks/deleted', { params }),
  restore: (id) => apiClient.post(`/api/v1/tasks/${id}/restore`),
})

export const createRoadmapApi = (apiClient) => ({
  get: (productId) => apiClient.get('/api/v1/roadmap', { params: seriesProductIdParam(productId) }),
  reorder: (items, productId) =>
    apiClient.patch('/api/v1/roadmap/reorder', { items }, { params: seriesProductIdParam(productId) }),
  removeItem: (itemId, productId) =>
    apiClient.delete(`/api/v1/roadmap/items/${itemId}`, { params: seriesProductIdParam(productId) }),
})
