import { apiClient } from './api.js'

export const sequenceRunsApi = {
  create: (data) => apiClient.post('/api/v1/sequence-runs', data),
  get: (runId) => apiClient.get(`/api/v1/sequence-runs/${runId}`),
  update: (runId, data) => apiClient.patch(`/api/v1/sequence-runs/${runId}`, data),
  list: (params = {}) => apiClient.get('/api/v1/sequence-runs', { params }),
  release: (runId, mode) => apiClient.post(`/api/v1/sequence-runs/${runId}/release`, null, { params: { mode } }),
  deactivate: (runId) => apiClient.post(`/api/v1/sequence-runs/${runId}/deactivate`),
  stop: (runId) => apiClient.post(`/api/v1/sequence-runs/${runId}/stop`),
  markReviewed: (runId, projectId) =>
    apiClient.post(`/api/v1/sequence-runs/${runId}/members/${projectId}/review`),
}
