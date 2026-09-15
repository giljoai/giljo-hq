import axios from 'axios'
import { API_CONFIG, getDefaultTenantKey } from '@/config/api'
import { parseErrorResponse, getErrorMessage } from '@/utils/errorMessages'
import { sequenceRunsApi } from './sequenceRunsApi.js'
import { executionModeDefaultApi } from './settingsApi.js'
import { notificationPrefsApi } from './notificationPrefsApi.js'
import { promptsApi } from './promptsApi.js'
import { templatesApi, assignmentsApi } from './agentsApi.js'
import { handleAuthFailure, normalizeRejection } from './apiFailureHandling.js'

const apiClient = axios.create({
  baseURL: API_CONFIG.REST_API.baseURL,
  timeout: API_CONFIG.REST_API.timeout,
  headers: API_CONFIG.REST_API.headers,
  withCredentials: true,
  paramsSerializer: { indexes: null },
})

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported in tests/saas/ and tests/setup.js (both outside src/); rule's scan stops at src/ boundary
export function updateApiBaseURL(newBaseURL) {
  apiClient.defaults.baseURL = newBaseURL
}

let currentTenantKey = null

export function setTenantKey(tenantKey) {
  currentTenantKey = tenantKey
}

let isRefreshing = false
let refreshSubscribers = []

function onRefreshed() {
  const subscribers = refreshSubscribers
  refreshSubscribers = []
  subscribers.forEach((s) => s.onSuccess())
}

function onRefreshFailed() {
  const subscribers = refreshSubscribers
  refreshSubscribers = []
  subscribers.forEach((s) => s.onFailure())
}

function addRefreshSubscriber(subscriber) {
  refreshSubscribers.push(subscriber)
}

async function silentRefresh() {
  if (isRefreshing) return
  isRefreshing = true
  try {
    await apiClient.post('/api/auth/refresh')
  } catch {
    // Silent failure -- will be caught by 401 interceptor if token actually expired
  } finally {
    isRefreshing = false
    onRefreshed()
  }
}


function getCsrfToken() {
  const match = document.cookie.match(/csrf_token=([^;]+)/)
  return match ? match[1] : null
}

apiClient.interceptors.request.use(
  (config) => {
    if (!config.headers['X-Tenant-Key'] || !currentTenantKey) {
      config.headers['X-Tenant-Key'] = currentTenantKey || getDefaultTenantKey()
    }

    if (['post', 'put', 'patch', 'delete'].includes(config.method)) {
      const csrfToken = getCsrfToken()
      if (csrfToken) {
        config.headers['X-CSRF-Token'] = csrfToken
      }
    }

    return config
  },
  (error) => Promise.reject(error),
)

apiClient.interceptors.response.use(
  (response) => {
    const expiresIn = response.headers['x-token-expires-in']
    if (expiresIn && parseInt(expiresIn) < 21600 && !isRefreshing) {
      silentRefresh()
    }
    return response
  },
  async (rejection) => {
    const error = normalizeRejection(rejection)

    if (axios.isCancel(error)) {
      return Promise.reject(error)
    }

    const originalRequest = error.config

    const parsedError = parseErrorResponse(error)

    if (parsedError.isStructured) {
      console.error('[API] Structured error:', {
        errorCode: parsedError.errorCode,
        message: parsedError.message,
        context: parsedError.context,
        timestamp: parsedError.timestamp,
        status: parsedError.status,
      })

      if (parsedError.errors) {
        console.error('[API] Validation errors:', parsedError.errors)
      }
    } else if (error.response) {
      console.error('[API] Legacy error:', {
        status: error.response.status,
        message: error.response.data?.message || error.message,
        data: error.response.data,
      })
    } else {
      console.error('[API] Network error:', error.message)
    }

    if (error.response?.status === 401 && !originalRequest?._retry) {
      if (originalRequest?.meta?.requiresAuth === false) {
        return Promise.reject(error)
      }

      if (
        originalRequest?.url?.includes('/api/auth/refresh') ||
        originalRequest?.url?.includes('/api/auth/login')
      ) {
        return handleAuthFailure(error)
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          addRefreshSubscriber({
            onSuccess: () => {
              originalRequest._retry = true
              resolve(apiClient(originalRequest))
            },
            onFailure: () => reject(error),
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        await apiClient.post('/api/auth/refresh')
        isRefreshing = false
        onRefreshed()
        return apiClient(originalRequest)
      } catch {
        isRefreshing = false
        onRefreshFailed()
        return handleAuthFailure(error)
      }
    }

    if (error.response?.status === 403 && !originalRequest?._csrfRetry) {
      const detail = error.response?.data?.detail || ''
      if (detail.includes('CSRF')) {
        originalRequest._csrfRetry = true
        try {
          await apiClient.get('/api/v1/products/')
          const newToken = getCsrfToken()
          if (newToken) {
            originalRequest.headers['X-CSRF-Token'] = newToken
          }
          return apiClient(originalRequest)
        } catch {
          // GET failed too — fall through to normal 403 handling
        }
      }
      console.error('[API] Access forbidden:', {
        message: parsedError.message,
        context: parsedError.context,
      })
    }

    if (!error.response) {
      console.error('[API] Network error - server may be unreachable:', error.message)
    }

    return Promise.reject(error)
  },
)

const _requestDedupeState = new Map()

export function dedupedRequest(key, requestFn, { ttl = 0, force = false } = {}) {
  const entry = _requestDedupeState.get(key)
  if (entry?.pending) return entry.pending
  if (!force && ttl > 0 && entry && entry.pending === null && Date.now() - entry.time < ttl) {
    return Promise.resolve(entry.value)
  }
  const pending = Promise.resolve()
    .then(requestFn)
    .then((value) => {
      _requestDedupeState.set(key, { pending: null, value, time: Date.now() })
      return value
    })
    .catch((err) => {
      _requestDedupeState.delete(key)
      throw err
    })
  _requestDedupeState.set(key, { pending, value: entry?.value, time: entry?.time ?? 0 })
  return pending
}

// eslint-disable-next-line giljo-internal/no-orphaned-exports
export function __resetRequestDedupe() {
  _requestDedupeState.clear()
}

const seriesProductIdParam = (productId) => (productId ? { product_id: productId } : {})

export const api = {
  products: {
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
  },

  taxonomyTypes: {
    list: () => apiClient.get('/api/v1/taxonomy-types/'),
    create: (data) => apiClient.post('/api/v1/taxonomy-types/', data),
    update: (id, data) => apiClient.put(`/api/v1/taxonomy-types/${id}`, data),
    delete: (id) => apiClient.delete(`/api/v1/taxonomy-types/${id}`),
  },

  projectStatuses: {
    list: () => apiClient.get('/api/v1/project-statuses/'),
  },

  taskStatuses: {
    list: () => apiClient.get('/api/v1/task-statuses/'),
  },

  projects: {
    list: (params) => apiClient.get('/api/v1/projects/', { params }),
    get: (id) => apiClient.get(`/api/v1/projects/${id}`),
    review: (id) => apiClient.get(`/api/v1/projects/${id}/review`),
    getOrchestrator: (id) => apiClient.get(`/api/v1/projects/${id}/orchestrator`),
    getActive: (productId) =>
      apiClient.get('/api/v1/projects/active', { params: productId ? { product_id: productId } : {} }),
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
    launchImplementation: (id) =>
      apiClient.patch(`/api/agent-jobs/projects/${id}/launch-implementation`),
  },

  tasks: {
    list: (params = {}) => apiClient.get('/api/v1/tasks/', { params: { limit: 500, ...params } }),
    get: (id) => apiClient.get(`/api/v1/tasks/${id}/`),
    create: (data) => apiClient.post('/api/v1/tasks/', data),
    update: (id, data) => apiClient.put(`/api/v1/tasks/${id}/`, data),
    delete: (id) => apiClient.delete(`/api/v1/tasks/${id}/`),
    changeStatus: (id, status) => apiClient.patch(`/api/v1/tasks/${id}/status/`, { status }),
    convertToProject: (id) => apiClient.post(`/api/v1/tasks/${id}/convert`, {}),
    getDeleted: (params) => apiClient.get('/api/v1/tasks/deleted', { params }),
    restore: (id) => apiClient.post(`/api/v1/tasks/${id}/restore`),
  },

  users: {
    update: (userId, updates) => apiClient.patch(`/api/v1/users/${userId}`, updates),
    getFieldToggleConfig: () => apiClient.get('/api/v1/users/me/field-priority'),
    updateFieldToggleConfig: (config) => apiClient.put('/api/v1/users/me/field-priority', config),
    resetFieldToggleConfig: () => apiClient.post('/api/v1/users/me/field-priority/reset'),
  },

  account: {
    exportMyData: () => apiClient.post('/api/v1/account/export'),
  },

  visionDocuments: {
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
  },

  settings: {
    get: () => apiClient.get('/api/v1/config/'),

    getDatabase: () => apiClient.get('/api/v1/settings/database'),
    testDatabase: () => apiClient.get('/api/v1/config/health/database'),

    getGeneral: () => apiClient.get('/api/v1/settings/general'),
    updateGeneral: (data) => apiClient.put('/api/v1/settings/general', { settings: data }),
    getAgentSilenceThreshold: () =>
      apiClient.get('/api/v1/settings/system/agent-silence-threshold'),
    updateAgentSilenceThreshold: (minutes) =>
      apiClient.put('/api/v1/settings/system/agent-silence-threshold', {
        agent_silence_threshold_minutes: minutes,
      }),
    getAgentCheckinCadence: () =>
      apiClient.get('/api/v1/settings/system/agent-checkin-cadence'),
    updateAgentCheckinCadence: (minutes) =>
      apiClient.put('/api/v1/settings/system/agent-checkin-cadence', {
        agent_checkin_cadence_minutes: minutes,
      }),

    getCookieDomains: () => apiClient.get('/api/v1/user/settings/cookie-domains'),
    addCookieDomain: (domain) => apiClient.post('/api/v1/user/settings/cookie-domains', { domain }),
    removeCookieDomain: (domain) =>
      apiClient.delete('/api/v1/user/settings/cookie-domains', { data: { domain } }),

    ...executionModeDefaultApi,
    ...notificationPrefsApi,

    getHeadlessLaunch: () => apiClient.get('/api/v1/user/settings/headless-launch'),
    updateHeadlessLaunch: (allow) =>
      apiClient.put('/api/v1/user/settings/headless-launch', { allow_headless_launch: allow }),
  },

  health: {
    check: () => apiClient.get('/health'),
  },

  setup: {
    status: () => apiClient.get('/api/setup/status'),
  },

  templates: templatesApi,
  assignments: assignmentsApi,

  auth: {
    login: (username, password) => apiClient.post('/api/auth/login', { username, password }),
    logout: () => apiClient.post('/api/auth/logout'),
    me: () => apiClient.get('/api/auth/me'),
    register: (data) => apiClient.post('/api/auth/register', data),
    createFirstAdmin: (data) => apiClient.post('/api/auth/create-first-admin', data),
    listUsers: () => apiClient.get('/api/v1/users/'),
    updateUser: (userId, data) => apiClient.put(`/api/v1/users/${userId}`, data),
    changePassword: (userId, data) => apiClient.put(`/api/v1/users/${userId}/password`, data),
    checkFirstLogin: (username) => apiClient.post('/api/auth/check-first-login', { username }),
    completeFirstLogin: (data) => apiClient.post('/api/auth/complete-first-login', data),
    verifyPin: (data) => apiClient.post('/api/auth/verify-pin', data),
    verifyPinAndResetPassword: (data) =>
      apiClient.post('/api/auth/verify-pin-and-reset-password', data),
    updateSetupState: (payload) => apiClient.patch('/api/auth/me/setup-state', payload),
  },

  apiKeys: {
    list: () => apiClient.get('/api/auth/api-keys'),
    getActive: () => apiClient.get('/api/auth/api-keys/active'),
    create: (name) => apiClient.post('/api/auth/api-keys', { name }),
    delete: (keyId) => apiClient.delete(`/api/auth/api-keys/${keyId}`),
  },

  connect: {
    credentialStatus: () => apiClient.get('/api/connect/credential-status'),
    removeConnection: (harness) => apiClient.delete(`/api/connect/connections/${harness}`),
  },

  serena: {
    getStatus: () => apiClient.get('/api/serena/status'),
    toggle: (enabled) => apiClient.post('/api/serena/toggle', { use_in_prompts: enabled }),
  },

  git: {
    getSettings: () => apiClient.get('/api/git/settings'),
    toggle: (enabled) => apiClient.post('/api/git/toggle', { enabled }),
  },

  agentJobs: {
    list: (projectId) => apiClient.get('/api/agent-jobs/', { params: { project_id: projectId } }),
    get: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}`),
    spawn: (data) => apiClient.post('/api/agent-jobs/spawn', data),
    status: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}/status`),
    updateMission: (jobId, data) => apiClient.patch(`/api/jobs/${jobId}/mission`, data),

    simpleHandover: (jobId) => apiClient.post(`/api/agent-jobs/${jobId}/simple-handover`),

    messages: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}/messages`),
  },

  organizations: {
    list: () => apiClient.get('/api/organizations'),
    get: (orgId) => apiClient.get(`/api/organizations/${orgId}`),
    create: (data) => apiClient.post('/api/organizations', data),
    update: (orgId, data) => apiClient.put(`/api/organizations/${orgId}`, data),
    delete: (orgId) => apiClient.delete(`/api/organizations/${orgId}`),
    listMembers: (orgId) => apiClient.get(`/api/organizations/${orgId}/members`),
    inviteMember: (orgId, data) => apiClient.post(`/api/organizations/${orgId}/members`, data),
    changeMemberRole: (orgId, userId, data) =>
      apiClient.put(`/api/organizations/${orgId}/members/${userId}`, data),
    removeMember: (orgId, userId) =>
      apiClient.delete(`/api/organizations/${orgId}/members/${userId}`),
    transferOwnership: (orgId, data) =>
      apiClient.post(`/api/organizations/${orgId}/transfer`, data),
  },

  orchestrator: {
    launchProject: (data) => apiClient.post('/api/agent-jobs/launch-project', data),
  },

  prompts: promptsApi,

  system: {
    getOrchestratorPrompt: (productId = null) =>
      apiClient.get('/api/v1/system/orchestrator-prompt', { params: { product_id: productId } }),
    updateOrchestratorPrompt: (content, productId = null) =>
      apiClient.put('/api/v1/system/orchestrator-prompt', { content, product_id: productId }),
    resetOrchestratorPrompt: (productId = null) =>
      apiClient.post('/api/v1/system/orchestrator-prompt/reset', null, {
        params: { product_id: productId },
      }),
  },

  approvals: {
    listPending: (params) =>
      apiClient.get('/api/approvals/', { params: { status: 'pending', ...(params || {}) } }),
    decide: (approvalId, optionId) =>
      apiClient.post(`/api/approvals/${approvalId}/decide`, { option_id: optionId }),
  },

  notifications: {
    list: (params) => apiClient.get('/api/notifications', { params }),
    markRead: (id) => apiClient.patch(`/api/notifications/${id}/read`),
    markDismissed: (id) => apiClient.patch(`/api/notifications/${id}/dismiss`),
  },

  threads: {
    list: (params) => apiClient.get('/api/v1/threads', { params }),
    myTurn: () => apiClient.get('/api/v1/threads/my-turn'),
    markRead: (id) => apiClient.post(`/api/v1/threads/${id}/read`),
    attention: () => apiClient.get('/api/v1/threads/attention'),
    search: (params) => apiClient.get('/api/v1/threads/search', { params }),
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
  },

  stats: {
    getSystem: () => apiClient.get('/api/v1/stats/system'),
    getCallCounts: () => apiClient.get('/api/v1/stats/call-counts'),
    getDashboard: (productId) =>
      apiClient.get('/api/v1/stats/dashboard', { params: { product_id: productId } }),
  },

  roadmap: {
    get: () => apiClient.get('/api/v1/roadmap'),
    reorder: (items) => apiClient.patch('/api/v1/roadmap/reorder', { items }),
    removeItem: (itemId) => apiClient.delete(`/api/v1/roadmap/items/${itemId}`),
  },

  sequenceRuns: sequenceRunsApi,
}

export { parseErrorResponse, getErrorMessage }

export { apiClient }

export default api
