
export const createProductsApi = (apiClient, dedupedRequest) => ({
  list: (params) =>
    dedupedRequest(
      `products:list:${params ? JSON.stringify(params) : ''}`,
      () => apiClient.get('/api/v1/products/', { params }),
      { ttl: 1500 },
    ),
  get: (id) => apiClient.get(`/api/v1/products/${id}`),
  getDefault: () =>
    dedupedRequest('products:default', () => apiClient.get('/api/v1/products/refresh-active'), { ttl: 1500 }),
  setDefault: (id) => apiClient.post(`/api/v1/products/${id}/set-default`),
  create: (data) => {
    const payload = {
      name: data.name,
      description: data.description || null,
      project_path: data.project_path || null,
      target_platforms: data.target_platforms || ['all'],
      tech_stack: data.tech_stack || null,
      architecture: data.architecture || null,
      test_config: data.test_config || null,
      core_features: data.core_features || null,
      brand_guidelines: data.brand_guidelines || null,
    }
    return apiClient.post('/api/v1/products/', payload)
  },
  update: (id, data) => {
    const payload = {}
    if (data.name !== undefined) payload.name = data.name
    if (data.description !== undefined) payload.description = data.description
    if (data.project_path !== undefined) payload.project_path = data.project_path
    if (data.target_platforms !== undefined) payload.target_platforms = data.target_platforms
    if (data.tech_stack !== undefined) payload.tech_stack = data.tech_stack
    if (data.architecture !== undefined) payload.architecture = data.architecture
    if (data.test_config !== undefined) payload.test_config = data.test_config
    if (data.core_features !== undefined) payload.core_features = data.core_features
    if (data.brand_guidelines !== undefined) payload.brand_guidelines = data.brand_guidelines
    if (data.extraction_custom_instructions !== undefined)
      payload.extraction_custom_instructions = data.extraction_custom_instructions
    if (data.isActive !== undefined) payload.is_active = data.isActive
    return apiClient.put(`/api/v1/products/${id}`, payload)
  },
  delete: (id) => apiClient.delete(`/api/v1/products/${id}`),
  purge: (id) => apiClient.delete(`/api/v1/products/${id}/purge`),
  getCascadeImpact: (id) => apiClient.get(`/api/v1/products/${id}/cascade-impact`),

  activate: (id) => apiClient.post(`/api/v1/products/${id}/activate`),
  deactivate: (id) => apiClient.post(`/api/v1/products/${id}/deactivate`),
  getDeletedProducts: () => apiClient.get('/api/v1/products/deleted'),
  restoreProduct: (id) => apiClient.post(`/api/v1/products/${id}/restore`),
  getMemoryEntries: (productId, params) =>
    apiClient.get(`/api/v1/products/${productId}/memory-entries`, { params }),
  getTuningSections: (productId) =>
    apiClient.get(`/api/v1/products/${productId}/tuning/sections`),
  generateTuningPrompt: (productId, sections) =>
    apiClient.post(`/api/v1/products/${productId}/tuning/generate-prompt`, { sections }),
  getContextUpdateProject: (productId) =>
    apiClient.get(`/api/v1/products/${productId}/context_update_project`),
})

export const createVisionDocumentsApi = (apiClient) => ({
  listByProduct: (productId) =>
    apiClient.get(`/api/vision-documents/product/${productId}?active_only=false`),
  upload: (formData) => {
    return apiClient.post('/api/vision-documents/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  get: (documentId) => apiClient.get(`/api/vision-documents/${documentId}`),
  getAiSummary: (documentId, level) =>
    apiClient.get(`/api/vision-documents/${documentId}/ai-summary/${level}`),
  delete: (documentId) => apiClient.delete(`/api/vision-documents/${documentId}`),
  getDeletedByProduct: (productId) =>
    apiClient.get(`/api/vision-documents/product/${productId}/deleted`),
  restore: (documentId) => apiClient.post(`/api/vision-documents/${documentId}/restore`),
})

export const createStatsApi = (apiClient) => ({
  getCallCounts: () => apiClient.get('/api/v1/stats/call-counts'),
  getDashboard: (productId) =>
    apiClient.get('/api/v1/stats/dashboard', { params: { product_id: productId } }),
})
