/**
 * ADR-001: the REST base URL comes only from getApiBaseUrl(). When the resolver
 * says "same origin" (empty string) the app stays on relative URLs; it never
 * builds protocol://host:port from the backend's bind address.
 */
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn(() =>
      Promise.resolve({
        api: { protocol: 'http', host: '198.51.100.40', port: 7272 },
        websocket: {},
        security: {},
      }),
    ),
  },
}))

vi.mock('@/composables/useApiUrl', () => ({
  getApiBaseUrl: () => '',
  getWsBaseUrl: () => '',
}))

const updateApiBaseURL = vi.fn()
vi.mock('@/services/api', () => ({ updateApiBaseURL }))

import { API_CONFIG, initializeApiConfig } from '@/config/api'

describe('initializeApiConfig -- no host:port fallback', () => {
  it('keeps the same-origin base URL instead of the backend bind address', async () => {
    await initializeApiConfig()

    expect(API_CONFIG.REST_API.baseURL).toBe('')
    expect(updateApiBaseURL).toHaveBeenCalledWith('')
  })
})
