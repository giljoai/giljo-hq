import axios from 'axios'
import { API_CONFIG, getDefaultTenantKey } from '@/config/api'
import { parseErrorResponse, getErrorMessage } from '@/utils/errorMessages'
import { sequenceRunsApi } from './sequenceRunsApi.js'
import { handleAuthFailure, normalizeRejection } from './apiFailureHandling.js'

// Create axios instance with default config
const apiClient = axios.create({
  baseURL: API_CONFIG.REST_API.baseURL,
  timeout: API_CONFIG.REST_API.timeout,
  headers: API_CONFIG.REST_API.headers,
  withCredentials: true, // CRITICAL: Send cookies with requests for JWT auth
  // FastAPI binds repeatable query params (e.g. `statuses: list[str]`) to the
  // BARE key — `?statuses=completed&statuses=active`. Axios 1.x's default
  // serializer emits bracketed `statuses[]=completed`, which FastAPI does NOT
  // bind, so the param silently drops to None and the endpoint falls back to
  // its default branch. (Repro: the Projects-page Status multi-select returned
  // the active-lifecycle default regardless of selection — picking "completed"
  // showed inactive rows.) `indexes: null` switches arrays to the unbracketed
  // repeat form FastAPI expects. Scalars are unaffected. The whole backend is
  // FastAPI, so this is correct API-wide, not just for /projects.
  paramsSerializer: { indexes: null },
})

// Export function to update baseURL after runtime config is fetched
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported in tests/saas/ and tests/setup.js (both outside src/); rule's scan stops at src/ boundary
export function updateApiBaseURL(newBaseURL) {
  apiClient.defaults.baseURL = newBaseURL
}

// Store current tenant key (set by user store after login)
let currentTenantKey = null

export function setTenantKey(tenantKey) {
  currentTenantKey = tenantKey
}

// Token refresh state (prevents concurrent refresh races).
// FE-9175: subscribers carry BOTH settlement paths. The old shape stored only
// a success callback, so a failed refresh cleared the list without settling
// the parked promises and every awaiting caller hung forever.
let isRefreshing = false
let refreshSubscribers = [] // { onSuccess, onFailure } pairs

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
    // FE-9175: requests that 401'd while this silent refresh was in flight are
    // parked in refreshSubscribers; flush them so none hang. If the refresh
    // actually failed, the retry re-401s and rejects normally (_retry is set).
    onRefreshed()
  }
}

// handleAuthFailure + normalizeRejection live in apiFailureHandling.js
// (FE-9175 extraction, 800-line guardrail -- see that module's header).

// Read CSRF token from cookie (double-submit cookie pattern)
function getCsrfToken() {
  const match = document.cookie.match(/csrf_token=([^;]+)/)
  return match ? match[1] : null
}

// Request interceptor for tenant key and CSRF token
// NOTE: Authentication token is sent automatically via httpOnly cookie (access_token)
// No need to manually add Authorization header - the browser handles this
apiClient.interceptors.request.use(
  (config) => {
    // Use current tenant key if set (from user store after login)
    // Otherwise fallback to default for pre-auth requests
    if (!config.headers['X-Tenant-Key'] || !currentTenantKey) {
      config.headers['X-Tenant-Key'] = currentTenantKey || getDefaultTenantKey()
    }

    // Add CSRF token for state-changing requests (Handover 0765f)
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

// Response interceptor for error handling and token refresh
apiClient.interceptors.response.use(
  (response) => {
    // Proactive token refresh: renew when less than 6 hours remaining
    const expiresIn = response.headers['x-token-expires-in']
    if (expiresIn && parseInt(expiresIn) < 21600 && !isRefreshing) {
      silentRefresh()
    }
    return response
  },
  async (rejection) => {
    const error = normalizeRejection(rejection)

    // Cancellation is a caller decision, not a failure: pass it through
    // untouched so axios.isCancel() keeps working at call sites and no
    // logging/auth path runs on it.
    if (axios.isCancel(error)) {
      return Promise.reject(error)
    }

    const originalRequest = error.config

    // Parse error response (handles both structured and legacy errors)
    const parsedError = parseErrorResponse(error)

    // Log structured errors for debugging
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

    // Handle 401 Unauthorized with silent refresh
    if (error.response?.status === 401 && !originalRequest?._retry) {
      // IMP-0013 #9: route-meta opt-out. Call sites can pass
      //   axios(url, { meta: { requiresAuth: false } })
      // to suppress the auto-redirect-to-/login behavior. Used by guard-like
      // probes (e.g. trial-status checks) that legitimately 401 for anon users
      // and must NOT bounce the browser. The implicit registration-order
      // contract is documented in saas/composables/useTrialGuard.js.
      if (originalRequest?.meta?.requiresAuth === false) {
        return Promise.reject(error)
      }

      // Don't attempt refresh for auth endpoints themselves
      if (
        originalRequest?.url?.includes('/api/auth/refresh') ||
        originalRequest?.url?.includes('/api/auth/login')
      ) {
        return handleAuthFailure(error)
      }

      if (isRefreshing) {
        // Another request is already refreshing -- park this one until the
        // refresh settles. FE-9175: wire BOTH outcomes; a failed refresh must
        // reject the parked promise (with this caller's own 401), never
        // strand it.
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
        // FE-9175: settle every parked request BEFORE redirecting -- each
        // rejects with its own original 401 so callers surface an error
        // instead of hanging on a promise nobody will ever settle.
        onRefreshFailed()
        return handleAuthFailure(error)
      }
    }

    // Handle 403 Forbidden — auto-retry on CSRF token mismatch
    if (error.response?.status === 403 && !originalRequest?._csrfRetry) {
      const detail = error.response?.data?.detail || ''
      if (detail.includes('CSRF')) {
        // CSRF token expired or missing — fetch a fresh one via GET then retry
        originalRequest._csrfRetry = true
        try {
          await apiClient.get('/api/v1/products/') // lightweight GET to receive new csrf_token cookie (must not be CSRF-exempt)
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

    // Handle network errors
    if (!error.response) {
      console.error('[API] Network error - server may be unreachable:', error.message)
    }

    return Promise.reject(error)
  },
)

// ---------------------------------------------------------------------------
// In-flight request de-duplication + short TTL (FE-6059, perf-findings 2026-06-11).
//
// Mirrors setupService's _statusPending/_statusCache precedent: collapse
// duplicate *concurrent* GETs to the same endpoint into ONE network request,
// and serve a just-fetched response for a short TTL so a burst of
// near-simultaneous reads across components / a route transition resolves to a
// single call. This is NOT a new cache "layer" — it is the same thin
// pending-promise + timestamp pattern setupService already uses, lifted into a
// helper so the two highest-traffic reads (products list 179-215x, SaaS
// account/status 370x per session) can share it. Keyed by a caller string so
// parameterized calls never collide; `force` bypasses the TTL for
// freshness-critical reads (e.g. a post-mutation refetch).
// ---------------------------------------------------------------------------
const _requestDedupeState = new Map() // key -> { pending: Promise|null, value, time }

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

// Test-only: clear de-dupe state between specs (module-level Map persists across
// tests in a worker). Imported only by requestDedupe.spec.js, which the
// orphaned-exports rule's src/ scan does not count — suppress the false positive.
// eslint-disable-next-line giljo-internal/no-orphaned-exports
export function __resetRequestDedupe() {
  _requestDedupeState.clear()
}

// API Service Methods
export const api = {
  // Products
  products: {
    // FE-6059: de-duped + short-TTL. A Home load and a Home->Projects
    // transition each fire products.list 3-4x near-simultaneously; in-flight
    // sharing collapses the concurrent burst and the brief TTL absorbs the
    // back-to-back transition reads. Writes update the store's local list
    // directly (createProduct/deleteProduct) and WS events resync, so a 1.5s
    // window of staleness on a passive re-read is safe.
    list: (params) =>
      dedupedRequest(
        `products:list:${params ? JSON.stringify(params) : ''}`,
        () => apiClient.get('/api/v1/products/', { params }),
        { ttl: 1500 },
      ),
    get: (id) => apiClient.get(`/api/v1/products/${id}`),
    getActive: () => apiClient.get('/api/v1/products/refresh-active'),
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

    // Product activation endpoints (Handover 0049)
    activate: (id) => apiClient.post(`/api/v1/products/${id}/activate`),
    deactivate: (id) => apiClient.post(`/api/v1/products/${id}/deactivate`),
    // Soft delete recovery endpoints
    getDeletedProducts: () => apiClient.get('/api/v1/products/deleted'),
    restoreProduct: (id) => apiClient.post(`/api/v1/products/${id}/restore`),
    // 360 Memory endpoints (Handover 0490)
    getMemoryEntries: (productId, params) =>
      apiClient.get(`/api/v1/products/${productId}/memory-entries`, { params }),
    // Product Context Tuning endpoints (Handover 0831)
    getTuningSections: (productId) =>
      apiClient.get(`/api/v1/products/${productId}/tuning/sections`),
    generateTuningPrompt: (productId, sections) =>
      apiClient.post(`/api/v1/products/${productId}/tuning/generate-prompt`, { sections }),
    // BE-5122 / FE-5073: Idempotency lookup for an open CTX (context-update)
    // project on the product. Returns 200 with hash_matches boolean if an open
    // CTX project exists, or 404 if none exists. Frontend uses this both to
    // avoid duplicate spawns and to short-circuit the create flow when the
    // hashes already match (server self-closes later, but we surface the
    // "already fresh" hint immediately when we know it).
    getContextUpdateProject: (productId) =>
      apiClient.get(`/api/v1/products/${productId}/context_update_project`),
  },

  // Taxonomy Types (renamed from project-types in Phase A of task agent-parity
  // taxonomy unification — the same taxonomy now serves both projects and
  // tasks, hence the rename. URL: /api/v1/taxonomy-types/.)
  taxonomyTypes: {
    list: () => apiClient.get('/api/v1/taxonomy-types/'),
    create: (data) => apiClient.post('/api/v1/taxonomy-types/', data),
    update: (id, data) => apiClient.put(`/api/v1/taxonomy-types/${id}`, data),
    delete: (id) => apiClient.delete(`/api/v1/taxonomy-types/${id}`),
  },

  // Project Statuses (BE-5039: Project Status SSOT)
  // Read-only — the canonical six statuses live in the backend
  // `ProjectStatus` enum. The endpoint returns metadata (label,
  // color_token, lifecycle flags) the frontend caches in
  // `projectStatusesStore` and consumes in StatusBadge / filters.
  projectStatuses: {
    list: () => apiClient.get('/api/v1/project-statuses/'),
  },

  // Task Statuses (FE-5041: Task Status SSOT, mirrors BE-5039 shape)
  // Read-only — the canonical six statuses live in the backend
  // `TaskStatus` enum. Endpoint returns metadata (label, color_token,
  // is_lifecycle_finished) consumed by `TaskStatusBadge` / Phase 2 store.
  taskStatuses: {
    list: () => apiClient.get('/api/v1/task-statuses/'),
  },

  // Projects
  projects: {
    list: (params) => apiClient.get('/api/v1/projects/', { params }),
    get: (id) => apiClient.get(`/api/v1/projects/${id}`),
    review: (id) => apiClient.get(`/api/v1/projects/${id}/review`),
    getOrchestrator: (id) => apiClient.get(`/api/v1/projects/${id}/orchestrator`),
    getActive: () => apiClient.get('/api/v1/projects/active'),
    create: (data) => apiClient.post('/api/v1/projects/', data),
    update: (id, data) => apiClient.patch(`/api/v1/projects/${id}`, data),
    delete: (id) => apiClient.delete(`/api/v1/projects/${id}`),
    fetchDeleted: (params) => apiClient.get('/api/v1/projects/deleted', { params }),
    // Taxonomy helpers (Handover 0440b)
    getNextSeries: (typeId) =>
      apiClient.get('/api/v1/projects/next-series', { params: { type_id: typeId } }),
    getAvailableSeries: (typeId, limit = 5) =>
      apiClient.get('/api/v1/projects/available-series', { params: { type_id: typeId, limit } }),
    checkSeries: (typeId, seriesNumber, subseries = null, excludeProjectId = null, options = {}) =>
      apiClient.get('/api/v1/projects/check-series', {
        params: {
          ...(typeId && { type_id: typeId }),
          series_number: seriesNumber,
          subseries,
          exclude_project_id: excludeProjectId,
        },
        ...options,
      }),
    usedSubseries: (typeId, seriesNumber, excludeProjectId = null, options = {}) =>
      apiClient.get('/api/v1/projects/used-subseries', {
        params: {
          ...(typeId && { type_id: typeId }),
          series_number: seriesNumber,
          exclude_project_id: excludeProjectId,
        },
        ...options,
      }),
    // Specific action endpoints (Handover 0507: Added force and reason parameters)
    activate: (id, force = false) => apiClient.post(`/api/v1/projects/${id}/activate`, { force }),
    deactivate: (id, reason = null) =>
      apiClient.post(`/api/v1/projects/${id}/deactivate`, { reason }),
    complete: (id) => apiClient.post(`/api/v1/projects/${id}/complete`),
    cancel: (id) => apiClient.post(`/api/v1/projects/${id}/cancel`),
    restore: (id) => apiClient.post(`/api/v1/projects/${id}/restore`),
    purgeDeleted: (id) => apiClient.delete(`/api/v1/projects/${id}/purge`),
    purgeAllDeleted: (params) => apiClient.delete('/api/v1/projects/deleted', { params }),
    // Completed projects are resumed via the continue-working endpoint
    restoreCompleted: (id) => apiClient.post(`/api/v1/projects/${id}/continue-working`),
    // Handover 0108: Staging cancellation
    cancelStaging: (id) => apiClient.post(`/api/v1/projects/${id}/cancel-staging`),
    // Restage: reset staging and create fresh orchestrator
    restage: (id) => apiClient.post(`/api/v1/projects/${id}/restage`),
    // FE-6180: Reset to original — destructive rewind (clears staging + hard-deletes
    // agents/jobs, no audit). Works on a launched project where restage refuses.
    reset: (id) => apiClient.post(`/api/v1/projects/${id}/reset`),
    // Unstage: revert from staged back to ready (before agent contact)
    unstage: (id) => apiClient.post(`/api/v1/projects/${id}/unstage`),
    // Closeout endpoints (Handover 0371, 0412)
    completeWithData: (id, data) => apiClient.post(`/api/v1/projects/${id}/complete`, data),
    archive: (id) => apiClient.post(`/api/v1/projects/${id}/archive`), // Handover 0412: Simple archive
    // Implementation phase gate (Handover 0709)
    launchImplementation: (id) =>
      apiClient.patch(`/api/agent-jobs/projects/${id}/launch-implementation`),
  },

  // Tasks
  tasks: {
    // BE-9141: pass a sane safety ceiling by default so the list read is bounded
    // (the endpoint caps at 500). Any explicit limit a caller passes wins.
    list: (params = {}) => apiClient.get('/api/v1/tasks/', { params: { limit: 500, ...params } }),
    get: (id) => apiClient.get(`/api/v1/tasks/${id}/`),
    create: (data) => apiClient.post('/api/v1/tasks/', data),
    update: (id, data) => apiClient.put(`/api/v1/tasks/${id}/`, data),
    delete: (id) => apiClient.delete(`/api/v1/tasks/${id}/`),
    changeStatus: (id, status) => apiClient.patch(`/api/v1/tasks/${id}/status/`, { status }),
    convertToProject: (id) => apiClient.post(`/api/v1/tasks/${id}/convert`, {}),
    // FE-6138: trash/recover (BE-6130b). getDeleted -> list[TaskResponse]; restore re-mints a serial.
    getDeleted: (params) => apiClient.get('/api/v1/tasks/deleted', { params }),
    restore: (id) => apiClient.post(`/api/v1/tasks/${id}/restore`),
  },

  // Users (for tenant user listing and assignment)
  // Handover 0506: Fixed paths to use /api/v1/users
  users: {
    update: (userId, updates) => apiClient.patch(`/api/v1/users/${userId}`, updates),
    // Field toggle configuration (Handover 0048, 0820)
    getFieldToggleConfig: () => apiClient.get('/api/v1/users/me/field-priority'),
    updateFieldToggleConfig: (config) => apiClient.put('/api/v1/users/me/field-priority', config),
    resetFieldToggleConfig: () => apiClient.post('/api/v1/users/me/field-priority/reset'),
  },

  // Account-level actions (Danger Zone). BE-5062: GDPR data portability —
  // CE-only. The backend gates the endpoint server-side; the frontend hides
  // the affordance in saas/demo to avoid surfacing a button that always 403s.
  // Response: { download_url, expires_at, model_counts }. Download URL TTL 15 min.
  account: {
    exportMyData: () => apiClient.post('/api/v1/account/export'),
  },

  // Vision Documents (Multi-Document Support - Handover 0043)
  visionDocuments: {
    // List all vision documents for a product
    listByProduct: (productId) =>
      apiClient.get(`/api/vision-documents/product/${productId}?active_only=false`),
    // Upload a new vision document (accepts FormData)
    upload: (formData) => {
      return apiClient.post('/api/vision-documents/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    // Get a single vision document by ID (full content + summaries)
    get: (documentId) => apiClient.get(`/api/vision-documents/${documentId}`),
    // Get AI summary content for a document at a given level ('light' or 'medium')
    getAiSummary: (documentId, level) =>
      apiClient.get(`/api/vision-documents/${documentId}/ai-summary/${level}`),
    // Delete a vision document
    delete: (documentId) => apiClient.delete(`/api/vision-documents/${documentId}`),
    // FE-6138: trash/recover (BE-6130b). getDeletedByProduct -> list[VisionDocumentResponse];
    // restore recovers the doc + its chunks as one unit.
    getDeletedByProduct: (productId) =>
      apiClient.get(`/api/vision-documents/product/${productId}/deleted`),
    restore: (documentId) => apiClient.post(`/api/vision-documents/${documentId}/restore`),
  },

  // Settings & Configuration
  // Handover 0506: Added new settings endpoints (general, network, database, product-info, cookie-domain)
  settings: {
    // Legacy config endpoint (kept for backward compatibility)
    get: () => apiClient.get('/api/v1/config/'),

    getDatabase: () => apiClient.get('/api/v1/settings/database'),
    testDatabase: () => apiClient.get('/api/v1/config/health/database'),

    // General settings (Settings table, not legacy config)
    getGeneral: () => apiClient.get('/api/v1/settings/general'),
    updateGeneral: (data) => apiClient.put('/api/v1/settings/general', { settings: data }),
    getAgentSilenceThreshold: () =>
      apiClient.get('/api/v1/settings/system/agent-silence-threshold'),
    updateAgentSilenceThreshold: (minutes) =>
      apiClient.put('/api/v1/settings/system/agent-silence-threshold', {
        agent_silence_threshold_minutes: minutes,
      }),

    // User settings - cookie domain management
    getCookieDomains: () => apiClient.get('/api/v1/user/settings/cookie-domains'),
    addCookieDomain: (domain) => apiClient.post('/api/v1/user/settings/cookie-domains', { domain }),
    removeCookieDomain: (domain) =>
      apiClient.delete('/api/v1/user/settings/cookie-domains', { data: { domain } }),

    // BE-9084: account-wide Headless-vs-HITL launch toggle
    getHeadlessLaunch: () => apiClient.get('/api/v1/user/settings/headless-launch'),
    updateHeadlessLaunch: (allow) =>
      apiClient.put('/api/v1/user/settings/headless-launch', { allow_headless_launch: allow }),
  },

  // Health Check (includes skills_version)
  health: {
    check: () => apiClient.get('/health'),
  },

  // Setup Status
  setup: {
    status: () => apiClient.get('/api/setup/status'),
  },

  // Templates (tenant-scoped — no product_id params)
  templates: {
    list: () => apiClient.get('/api/v1/templates/'),
    get: (id) => apiClient.get(`/api/v1/templates/${id}`),
    create: (data) => apiClient.post('/api/v1/templates/', data),
    update: (id, data) => apiClient.put(`/api/v1/templates/${id}`, data),
    delete: (id) => apiClient.delete(`/api/v1/templates/${id}`),
    history: (id, limit = 10) =>
      apiClient.get(`/api/v1/templates/${id}/history/`, { params: { limit } }),
    // Handover 0396: Added optional reason parameter for restore operation
    restore: (templateId, archiveId, reason = null) => {
      const payload = reason ? { reason } : {}
      return apiClient.post(`/api/v1/templates/${templateId}/restore/${archiveId}/`, payload)
    },
    preview: (id, data = {}) => apiClient.post(`/api/v1/templates/${id}/preview/`, data),
    reset: (id) => apiClient.post(`/api/v1/templates/${id}/reset/`),
    activeCount: () => apiClient.get('/api/v1/templates/stats/active-count'),
    // FE-9203: additive import of the seeded default agents (no body)
    importDefaults: () => apiClient.post('/api/v1/templates/import-defaults'),
  },

  // Per-product agent assignments (junction table toggle)
  assignments: {
    list: (productId) => apiClient.get(`/api/products/${productId}/agent-assignments`),
    toggle: (productId, templateId, isActive) =>
      apiClient.put(`/api/products/${productId}/agent-assignments/${templateId}`, {
        is_active: isActive,
      }),
  },

  // Authentication (JWT via httpOnly cookies)
  auth: {
    login: (username, password) => apiClient.post('/api/auth/login', { username, password }),
    logout: () => apiClient.post('/api/auth/logout'),
    me: () => apiClient.get('/api/auth/me'),
    register: (data) => apiClient.post('/api/auth/register', data),
    // REMOVED (Handover 0034): changePassword - legacy admin/admin flow
    // Replaced by createFirstAdmin for fresh installs
    createFirstAdmin: (data) => apiClient.post('/api/auth/create-first-admin', data),
    listUsers: () => apiClient.get('/api/v1/users/'), // 0371: Fixed - was /api/auth/users (missing PUT/DELETE)
    updateUser: (userId, data) => apiClient.put(`/api/v1/users/${userId}`, data),
    // IMP-5042: self-service password change. PUT /users/{id}/password requires
    // the current password and revokes the caller's own session on success
    // (SEC-6001), so the caller must sign in again afterwards.
    changePassword: (userId, data) => apiClient.put(`/api/v1/users/${userId}/password`, data),
    // Password reset endpoints (Handover 0023)
    checkFirstLogin: (username) => apiClient.post('/api/auth/check-first-login', { username }),
    completeFirstLogin: (data) => apiClient.post('/api/auth/complete-first-login', data),
    verifyPin: (data) => apiClient.post('/api/auth/verify-pin', data),
    verifyPinAndResetPassword: (data) =>
      apiClient.post('/api/auth/verify-pin-and-reset-password', data),
    updateSetupState: (payload) => apiClient.patch('/api/auth/me/setup-state', payload),
  },

  // API Key Management
  apiKeys: {
    list: () => apiClient.get('/api/auth/api-keys'),
    getActive: () => apiClient.get('/api/auth/api-keys/active'),
    create: (name) => apiClient.post('/api/auth/api-keys', { name }),
    delete: (keyId) => apiClient.delete(`/api/auth/api-keys/${keyId}`),
  },

  // Connect surface — durable credential status (FE-9274)
  connect: {
    credentialStatus: () => apiClient.get('/api/connect/credential-status'),
  },

  // Serena MCP Integration
  serena: {
    getStatus: () => apiClient.get('/api/serena/status'),
    toggle: (enabled) => apiClient.post('/api/serena/toggle', { use_in_prompts: enabled }),
  },

  // Git Integration (system-level)
  git: {
    getSettings: () => apiClient.get('/api/git/settings'),
    toggle: (enabled) => apiClient.post('/api/git/toggle', { enabled }),
  },

  // Agent Jobs API (Handover 0119 Phase 1 - Migration from /api/v1/agents)
  // Reference: internal design notes
  // Field mappings: agent_id → job_id, created_at → spawned_at, status → job status
  agentJobs: {
    // Core job management (maps from old agents API)
    list: (projectId) => apiClient.get('/api/agent-jobs/', { params: { project_id: projectId } }),
    get: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}`),
    spawn: (data) => apiClient.post('/api/agent-jobs/spawn', data),
    status: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}/status`),
    // Mission update endpoint (Handover 0244b). Route lives under /api/jobs
    // (operations.router is mounted only there, not under /api/agent-jobs) --
    // see tests/unit/test_be6042b_app_surface.py for the mounted route table.
    updateMission: (jobId, data) => apiClient.patch(`/api/jobs/${jobId}/mission`, data),

    // Handover 0461d: Simple handover - reset context and get continuation prompt
    // NOTE: Legacy succession endpoints (triggerSuccession, checkSuccessionStatus, initiateHandover)
    // removed in Handover 0700d. Use simpleHandover instead.
    simpleHandover: (jobId) => apiClient.post(`/api/agent-jobs/${jobId}/simple-handover`),

    // Message and communication endpoints (Handover 0066 - Kanban Dashboard)
    messages: (jobId) => apiClient.get(`/api/agent-jobs/${jobId}/messages`),
    // FE-6174c: getRoster (Mission Control roster) removed with the retirement of
    // Mission Control + missionControlStore — it had no other consumer.
  },

  // Organizations (Handover 0424 - gap fix)
  organizations: {
    list: () => apiClient.get('/api/organizations'),
    get: (orgId) => apiClient.get(`/api/organizations/${orgId}`),
    create: (data) => apiClient.post('/api/organizations', data),
    update: (orgId, data) => apiClient.put(`/api/organizations/${orgId}`, data),
    delete: (orgId) => apiClient.delete(`/api/organizations/${orgId}`),
    // Member operations
    listMembers: (orgId) => apiClient.get(`/api/organizations/${orgId}/members`),
    inviteMember: (orgId, data) => apiClient.post(`/api/organizations/${orgId}/members`, data),
    changeMemberRole: (orgId, userId, data) =>
      apiClient.put(`/api/organizations/${orgId}/members/${userId}`, data),
    removeMember: (orgId, userId) =>
      apiClient.delete(`/api/organizations/${orgId}/members/${userId}`),
    transferOwnership: (orgId, data) =>
      apiClient.post(`/api/organizations/${orgId}/transfer`, data),
  },

  // Orchestrator (Multi-Agent Workflow Coordination)
  orchestrator: {
    launchProject: (data) => apiClient.post('/api/agent-jobs/launch-project', data),
  },

  // Prompts (Handover 0119 Phase 1 - Standardized to /api/v1/prompts)
  // Reference: internal design notes
  prompts: {
    staging: (projectId, params) =>
      apiClient.get(`/api/v1/prompts/staging/${projectId}`, { params }),
    agentPrompt: (agentJobId) => apiClient.get(`/api/v1/prompts/agent/${agentJobId}`),
    // Handover 0344: CLI mode implementation prompt for orchestrator play button
    implementation: (projectId) => apiClient.get(`/api/v1/prompts/implementation/${projectId}`),
    // Handover 0498: Termination prompt for early project shutdown
    termination: (projectId) => apiClient.get(`/api/v1/prompts/termination/${projectId}`),
    // FE-6165f: chain (sequence-run-scoped) kickoff prompts. RUN-scoped (run_id),
    // distinct from the project-scoped staging/implementation above. BE-6165d
    // returns ChainPromptResponse { run_id, head_project_id, orchestrator_job_id,
    // prompt }; the Stage Chain / Implement Chain buttons copy `data.prompt`.
    chainStaging: (runId) => apiClient.get(`/api/v1/prompts/chain-staging/${runId}`),
    chainImplementation: (runId) => apiClient.get(`/api/v1/prompts/chain-implementation/${runId}`),
    // Handover 0396: Orchestrator prompt for copy-to-clipboard (Claude Code or Codex/Gemini)
    orchestrator: (tool, projectId) =>
      apiClient.get(`/api/v1/prompts/orchestrator/${tool}`, {
        params: { project_id: projectId },
      }),
  },

  system: {
    getOrchestratorPrompt: () => apiClient.get('/api/v1/system/orchestrator-prompt'),
    updateOrchestratorPrompt: (content) =>
      apiClient.put('/api/v1/system/orchestrator-prompt', { content }),
    resetOrchestratorPrompt: () => apiClient.post('/api/v1/system/orchestrator-prompt/reset'),
  },

  // User Approvals (FE-5017 Phase C)
  // Backend: api/endpoints/approvals.py — POST /api/approvals/{id}/decide
  // List endpoint (GET /api/approvals) is added by the backend implementer in
  // the same phase; consumed here by useApprovalsStore for the dashboard inbox.
  approvals: {
    listPending: (params) =>
      apiClient.get('/api/approvals/', { params: { status: 'pending', ...(params || {}) } }),
    decide: (approvalId, optionId) =>
      apiClient.post(`/api/approvals/${approvalId}/decide`, { option_id: optionId }),
  },

  // Notifications (IMP-5037a — DB-backed bell)
  notifications: {
    list: (params) => apiClient.get('/api/notifications', { params }),
    markRead: (id) => apiClient.patch(`/api/notifications/${id}/read`),
    markDismissed: (id) => apiClient.patch(`/api/notifications/${id}/dismiss`),
  },

  // Threads — Agent Message Hub (FE-6054e)
  // IMPORTANT: list and create are at /api/v1/threads with NO trailing slash.
  threads: {
    list: (params) => apiClient.get('/api/v1/threads', { params }),
    myTurn: () => apiClient.get('/api/v1/threads/my-turn'),
    search: (params) => apiClient.get('/api/v1/threads/search', { params }),
    // FE-9012c: include_recipient_state surfaces per-message junction state
    // (recipients/acked_by/completed_by/pending_for) for the in-thread waiting/read/sent filter.
    history: (id, { includeRecipientState = false } = {}) =>
      apiClient.get(`/api/v1/threads/${id}`, {
        params: includeRecipientState ? { include_recipient_state: true } : undefined,
      }),
    participants: (id) => apiClient.get(`/api/v1/threads/${id}/participants`),
    create: (body) => apiClient.post('/api/v1/threads', body),
    // FE-9289c: rename and/or set status (BE-9289b PATCH). Rejected on project threads.
    update: (id, body) => apiClient.patch(`/api/v1/threads/${id}`, body),
    post: (id, body) => apiClient.post(`/api/v1/threads/${id}/post`, body),
    passBaton: (id, to) => apiClient.post(`/api/v1/threads/${id}/baton`, { to }),
    delete: (id) => apiClient.delete(`/api/v1/threads/${id}`),
    // FE-6138: trash/recover (BE-6130b). getDeleted -> {count, threads}; restore re-broadcasts WS.
    getDeleted: (params) => apiClient.get('/api/v1/threads/deleted', { params }),
    restore: (id) => apiClient.post(`/api/v1/threads/${id}/restore`),
  },

  // Statistics
  stats: {
    getSystem: () => apiClient.get('/api/v1/stats/system'),
    getCallCounts: () => apiClient.get('/api/v1/stats/call-counts'),
    getDashboard: (productId) =>
      apiClient.get('/api/v1/stats/dashboard', { params: { product_id: productId } }),
  },

  // Roadmap (FE-6022b — binds to FE-6022a backend contract)
  // GET returns the active product's single roadmap: { product_id, roadmap, items[] }
  //   - 404 when no product is active; 200 with roadmap:null/items:[] when none exists yet.
  //   - items are priority-sorted ascending; each item.id is the reorder handle.
  // PATCH /reorder persists a new ordering. Wire key is `items`; priority is 0..100000.
  //   - unknown/cross-tenant ids are silently skipped server-side.
  roadmap: {
    get: () => apiClient.get('/api/v1/roadmap'),
    reorder: (items) => apiClient.patch('/api/v1/roadmap/reorder', { items }),
    // FE-6022c-polish: remove ONE item from the active product's roadmap.
    // Tenant + active-product scoped server-side; deletes only the roadmap_item,
    // never the underlying project/task. Unknown/cross-tenant id is a no-op.
    removeItem: (itemId) => apiClient.delete(`/api/v1/roadmap/items/${itemId}`),
  },

  // Sequence Runs — extracted to sequenceRunsApi.js (800-line guardrail).
  sequenceRuns: sequenceRunsApi,
}

// Export error handling utilities for use in components (Handover 0480f)
export { parseErrorResponse, getErrorMessage }

// Export the raw axios instance for components needing direct HTTP calls with CSRF/tenant headers
export { apiClient }

export default api
