// eslint-allow giljo-internal/no-manual-api-url-composition
import configService from '@/services/configService'
import { getApiBaseUrl, getWsBaseUrl } from '@/composables/useApiUrl'

const DEFAULT_BASE_URL = getApiBaseUrl()
const DEFAULT_WS_URL = import.meta.env.VITE_WS_URL || getWsBaseUrl()

let runtimeConfig = null

export async function initializeApiConfig() {
  try {
    const backendConfig = await configService.fetchConfig()

    runtimeConfig = {
      api: backendConfig.api,
      websocket: backendConfig.websocket,
      mode: backendConfig.mode,
      security: backendConfig.security,
    }

    const resolvedBase = getApiBaseUrl()
    const apiProtocol =
      runtimeConfig.api?.protocol || (typeof window !== 'undefined' && window.location?.protocol === 'https:' ? 'https' : 'http')
    const backendBase =
      runtimeConfig.api?.host && runtimeConfig.api?.port
        ? `${apiProtocol}://${runtimeConfig.api.host}:${runtimeConfig.api.port}`
        : ''
    const newBaseURL = resolvedBase || backendBase

    API_CONFIG.REST_API.baseURL = newBaseURL
    API_CONFIG.WEBSOCKET.url = runtimeConfig.websocket?.url || getWsBaseUrl() || DEFAULT_WS_URL

    if (runtimeConfig.security?.default_tenant_key) {
      API_CONFIG.REST_API.headers['X-Tenant-Key'] = runtimeConfig.security.default_tenant_key
    }

    const { updateApiBaseURL } = await import('@/services/api')
    updateApiBaseURL(newBaseURL)

    return true
  } catch (error) {
    console.error('[API Config] Failed to initialize from backend, using fallback:', error)
    return false
  }
}

export function getRuntimeConfig() {
  return runtimeConfig
}

export function getApiBaseURL() {
  return window.API_BASE_URL || API_CONFIG.REST_API.baseURL || getApiBaseUrl()
}

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
