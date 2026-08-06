// eslint-allow giljo-internal/no-manual-api-url-composition
// (sanctioned: dev-mode fallback only — see resolver path in updateApiBaseURL below)
// API Configuration for Giljo HQ Dashboard
//
// URL composition is centralised in @/composables/useApiUrl. This module
// derives its defaults from the resolver and keeps runtime-updatable config
// objects for legacy callers. Never reconstruct URLs from hostname + port
// here — that was the mcp.example.com bug (VITE_API_PORT being appended to
// an absolute URL served through Cloudflare Tunnel).
import configService from '@/services/configService'
import { getApiBaseUrl, getWsBaseUrl } from '@/composables/useApiUrl'

const DEFAULT_BASE_URL = getApiBaseUrl()
const DEFAULT_WS_URL = import.meta.env.VITE_WS_URL || getWsBaseUrl()

// Configuration object that will be updated after fetching from backend
let runtimeConfig = null

/**
 * Initialize API configuration from backend
 * This should be called before the app mounts to ensure correct API host
 */
export async function initializeApiConfig() {
  try {
    // Fetch config from backend
    const backendConfig = await configService.fetchConfig()

    // Update runtime config with backend values
    runtimeConfig = {
      api: backendConfig.api,
      websocket: backendConfig.websocket,
      mode: backendConfig.mode,
      security: backendConfig.security,
    }

    // Prefer the resolver's base URL (handles demo / CE / dev uniformly).
    // Backend-provided host:port is only used as a fallback when the resolver
    // returns an empty string (dev mode with no VITE_API_URL / window override).
    const resolvedBase = getApiBaseUrl()
    const apiProtocol =
      runtimeConfig.api?.protocol || (typeof window !== 'undefined' && window.location?.protocol === 'https:' ? 'https' : 'http')
    const backendBase =
      runtimeConfig.api?.host && runtimeConfig.api?.port
        ? `${apiProtocol}://${runtimeConfig.api.host}:${runtimeConfig.api.port}`
        : ''
    const newBaseURL = resolvedBase || backendBase

    // Update API and WebSocket config
    API_CONFIG.REST_API.baseURL = newBaseURL
    API_CONFIG.WEBSOCKET.url = runtimeConfig.websocket?.url || getWsBaseUrl() || DEFAULT_WS_URL

    // Update default tenant key header from backend config
    if (runtimeConfig.security?.default_tenant_key) {
      API_CONFIG.REST_API.headers['X-Tenant-Key'] = runtimeConfig.security.default_tenant_key
    }

    // Update axios instance baseURL (created before config was fetched)
    // Import dynamically to avoid circular dependency
    const { updateApiBaseURL } = await import('@/services/api')
    updateApiBaseURL(newBaseURL)

    return true
  } catch (error) {
    console.error('[API Config] Failed to initialize from backend, using fallback:', error)
    return false
  }
}

/**
 * Get current runtime configuration
 * @returns {Object} Current configuration
 */
export function getRuntimeConfig() {
  return runtimeConfig
}

/**
 * Get the current API base URL (runtime-aware)
 * Always use this instead of API_CONFIG.REST_API.baseURL for fetch() calls
 * @returns {string} Current API base URL
 */
export function getApiBaseURL() {
  return window.API_BASE_URL || API_CONFIG.REST_API.baseURL || getApiBaseUrl()
}

/**
 * Get the default tenant key (runtime-aware)
 * Resolves from: runtime config (backend) > env var > empty string
 * @returns {string} Default tenant key
 */
export function getDefaultTenantKey() {
  return runtimeConfig?.security?.default_tenant_key || import.meta.env.VITE_DEFAULT_TENANT_KEY || ''
}

export const API_CONFIG = {
  REST_API: {
    baseURL: DEFAULT_BASE_URL,
    timeout: 30000,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-Key': import.meta.env.VITE_DEFAULT_TENANT_KEY || '',
    },
  },
  WEBSOCKET: {
    url: DEFAULT_WS_URL,
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 30000,
    reconnectionAttempts: 10,
    debug: import.meta.env.VITE_WS_DEBUG === 'true' || false,
  },
}
