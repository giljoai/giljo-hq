
const requireProductId = (productId) => {
  if (!productId) throw new Error('A product id is required for orchestrator prompt calls')
  return productId
}

export const createAgentJobsApi = (apiClient) => ({
  list: (projectId) => apiClient.get('/api/agent-jobs/', { params: { project_id: projectId } }),
  listMany: (projectIds) =>
    apiClient.get('/api/agent-jobs/', { params: { project_ids: projectIds.join(','), limit: 500 } }),
  get: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}`),
  spawn: (data) => apiClient.post('/api/agent-jobs/spawn', data),
  status: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}/status`),
  updateMission: (jobId, data) => apiClient.patch(`/api/jobs/${jobId}/mission`, data),

  messages: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}/messages`),
})

export const createOrchestratorApi = (apiClient) => ({
  launchProject: (data) => apiClient.post('/api/agent-jobs/launch-project', data),
})

export const createSystemApi = (apiClient) => ({
  getOrchestratorPrompt: (productId = null) =>
    apiClient.get('/api/v1/system/orchestrator-prompt', { params: { product_id: productId } }),
  updateOrchestratorPrompt: (additions, productId) =>
    apiClient.put('/api/v1/system/orchestrator-prompt', { additions, product_id: requireProductId(productId) }),
  resetOrchestratorPrompt: (productId) =>
    apiClient.post('/api/v1/system/orchestrator-prompt/reset', null, {
      params: { product_id: requireProductId(productId) },
    }),
})

export const createApprovalsApi = (apiClient) => ({
  listPending: (params) =>
    apiClient.get('/api/approvals/', { params: { status: 'pending', ...(params || {}) } }),
  decide: (approvalId, optionId) =>
    apiClient.post(`/api/approvals/${approvalId}/decide`, { option_id: optionId }),
})
