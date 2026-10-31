import axios from 'axios'
import { API_CONFIG, getDefaultTenantKey } from '@/config/api'
import { parseErrorResponse, getErrorMessage } from '@/utils/errorMessages'
import { sequenceRunsApi } from './sequenceRunsApi.js'
import { promptsApi } from './promptsApi.js'
import { templatesApi, assignmentsApi, templateProposalsApi } from './agentsApi.js'
import { handleAuthFailure, noteSignOutReason, normalizeRejection } from './apiFailureHandling.js'
import { createProductsApi, createVisionDocumentsApi, createStatsApi } from './api/products.js'
import {
  createTaxonomyTypesApi,
  createProjectStatusesApi,
  createTaskStatusesApi,
  createProjectsApi,
  createTasksApi,
  createRoadmapApi,
} from './api/projects.js'
import {
  createUsersApi,
  createAccountApi,
  createAuthApi,
  createApiKeysApi,
  createConnectedAppsApi,
  createConnectApi,
  createOrganizationsApi,
} from './api/accounts.js'
import { createSettingsApi, createHealthApi, createSetupApi, createGitApi } from './api/settings.js'
import {
  createAgentJobsApi,
  createOrchestratorApi,
  createSystemApi,
  createApprovalsApi,
} from './api/orchestration.js'
import { createNotificationsApi, createThreadsApi } from './api/messaging.js'

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


const PENDING_STEP_ROUTES = {
  PASSWORD_CHANGE_REQUIRED: '/first-login',
  TERMS_REACCEPTANCE_REQUIRED: '/reaccept-terms',
}

async function routeToPendingStep(errorCode) {
  const target = PENDING_STEP_ROUTES[errorCode]
  if (target && window.location.pathname !== target) {
    const { default: router } = await import('@/router')
    router.push(target)
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

    if (
      error.response?.status === 401 &&
      parsedError.errorCode === 'TERMS_REACCEPTANCE_REQUIRED' &&
      originalRequest?.meta?.requiresAuth !== false
    ) {
      await routeToPendingStep(parsedError.errorCode)
      return Promise.reject(error)
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
      } catch (refreshError) {
        isRefreshing = false
        noteSignOutReason(refreshError)
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

    if (error.response?.status === 403) {
      await routeToPendingStep(parsedError.errorCode)
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

export const api = {
  products: createProductsApi(apiClient, dedupedRequest),
  taxonomyTypes: createTaxonomyTypesApi(apiClient),
  projectStatuses: createProjectStatusesApi(apiClient),
  taskStatuses: createTaskStatusesApi(apiClient),
  projects: createProjectsApi(apiClient),
  tasks: createTasksApi(apiClient),
  users: createUsersApi(apiClient),
  account: createAccountApi(apiClient),
  visionDocuments: createVisionDocumentsApi(apiClient),
  settings: createSettingsApi(apiClient),
  health: createHealthApi(apiClient),
  setup: createSetupApi(apiClient),

  templates: templatesApi,
  assignments: assignmentsApi,
  templateProposals: templateProposalsApi,

  auth: createAuthApi(apiClient),
  apiKeys: createApiKeysApi(apiClient),
  connectedApps: createConnectedAppsApi(apiClient),
  connect: createConnectApi(apiClient),
  git: createGitApi(apiClient),
  agentJobs: createAgentJobsApi(apiClient),
  organizations: createOrganizationsApi(apiClient),
  orchestrator: createOrchestratorApi(apiClient),

  prompts: promptsApi,

  system: createSystemApi(apiClient),
  approvals: createApprovalsApi(apiClient),
  notifications: createNotificationsApi(apiClient),
  threads: createThreadsApi(apiClient),
  stats: createStatsApi(apiClient),
  roadmap: createRoadmapApi(apiClient),

  sequenceRuns: sequenceRunsApi,
}

export { parseErrorResponse, getErrorMessage }

export { apiClient }

export default api
