
export const createNotificationsApi = (apiClient) => ({
  list: (params) => apiClient.get('/api/notifications', { params }),
  markRead: (id) => apiClient.patch(`/api/notifications/${id}/read`),
  markDismissed: (id) => apiClient.patch(`/api/notifications/${id}/dismiss`),
})

export const createThreadsApi = (apiClient) => ({
  list: (params) => apiClient.get('/api/v1/threads', { params }),
  myTurn: () => apiClient.get('/api/v1/threads/my-turn'),
  markRead: (id) => apiClient.post(`/api/v1/threads/${id}/read`),
  attention: () => apiClient.get('/api/v1/threads/attention'),
  search: (params) => apiClient.get('/api/v1/threads/search', { params }),
  chainHub: (runId) => apiClient.get('/api/v1/threads/chain-hub', { params: { sequence_run_id: runId } }),
  history: (id, { includeRecipientState = false } = {}) =>
    apiClient.get(`/api/v1/threads/${id}`, {
      params: includeRecipientState ? { include_recipient_state: true } : undefined,
    }),
  participants: (id) => apiClient.get(`/api/v1/threads/${id}/participants`),
  create: (body) => apiClient.post('/api/v1/threads', body),
  update: (id, body) => apiClient.patch(`/api/v1/threads/${id}`, body),
  post: (id, body) => apiClient.post(`/api/v1/threads/${id}/post`, body),
  passBaton: (id, to) => apiClient.post(`/api/v1/threads/${id}/baton`, { to }),
  delete: (id) => apiClient.delete(`/api/v1/threads/${id}`),
  getDeleted: (params) => apiClient.get('/api/v1/threads/deleted', { params }),
  restore: (id) => apiClient.post(`/api/v1/threads/${id}/restore`),
})
