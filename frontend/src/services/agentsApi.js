import { apiClient } from './api.js'

export const templatesApi = {
  list: (productId = null) =>
    apiClient.get('/api/v1/templates/', productId ? { params: { product_id: productId } } : undefined),
  get: (id) => apiClient.get(`/api/v1/templates/${id}`),
  create: (data) => apiClient.post('/api/v1/templates/', data),
  update: (id, data) => apiClient.put(`/api/v1/templates/${id}`, data),
  delete: (id) => apiClient.delete(`/api/v1/templates/${id}`),
  history: (id, limit = 10) =>
    apiClient.get(`/api/v1/templates/${id}/history/`, { params: { limit } }),
  restore: (templateId, archiveId, reason = null) => {
    const payload = reason ? { reason } : {}
    return apiClient.post(`/api/v1/templates/${templateId}/restore/${archiveId}/`, payload)
  },
  preview: (id, data = {}) => apiClient.post(`/api/v1/templates/${id}/preview/`, data),
  reset: (id) => apiClient.post(`/api/v1/templates/${id}/reset/`),
  activeCount: (productId) =>
    apiClient.get('/api/v1/templates/stats/active-count', { params: { product_id: productId } }),
  profileDownloadUrl: (id) => `/api/v1/templates/${id}/profile.md`,
  importDefaults: (productId) =>
    apiClient.post('/api/v1/templates/import-defaults', null, { params: { product_id: productId } }),
}

export const assignmentsApi = {
  list: (productId) => apiClient.get(`/api/v1/products/${productId}/agent-assignments`),
  toggle: (productId, templateId, isActive) =>
    apiClient.put(`/api/v1/products/${productId}/agent-assignments/${templateId}`, {
      is_active: isActive,
    }),
}
