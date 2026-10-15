/**
 * SEC-9758: a browser the server signed out because its person signed in on a
 * newer browser learns WHY. The refresh answer carries SESSION_DISPLACED; the
 * interceptor parks that reason across the redirect to /login so the login screen
 * can show it. A refresh that fails for any other reason must park nothing.
 *
 * Same strategy as api.refresh-single-flight.spec.js: real module, fake adapter,
 * the registered response-error handler driven with a fabricated 401.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.unmock('@/services/api')

vi.mock('@/router', () => {
  const resolve = vi.fn((path) => {
    const normalized = String(path).split('?')[0]
    return { path: normalized, meta: { requiresAuth: normalized !== '/login' } }
  })
  return { default: { resolve, push: vi.fn(), currentRoute: { value: { meta: {} } } } }
})

vi.mock('@/services/setupService', () => ({
  default: { checkEnhancedStatus: vi.fn(() => Promise.resolve({ is_fresh_install: false })) },
}))

function make401(url, data = {}) {
  return Object.assign(new Error('Request failed with status code 401'), {
    isAxiosError: true,
    config: { url, method: 'get', headers: {} },
    response: { status: 401, data, headers: {} },
  })
}

async function setup(refreshFailure) {
  Object.defineProperty(window, 'location', {
    writable: true,
    configurable: true,
    value: { pathname: '/home', search: '' },
  })
  vi.resetModules()
  const { apiClient } = await import('@/services/api.js')
  apiClient.defaults.adapter = vi.fn((config) => {
    if (String(config.url).includes('/api/auth/refresh')) return Promise.reject(refreshFailure)
    return Promise.resolve({ data: {}, status: 200, statusText: 'OK', headers: {}, config })
  })
  const handlers = apiClient.interceptors.response.handlers.filter(Boolean)
  const { rejected } = handlers[handlers.length - 1]
  const failure = await import('@/services/apiFailureHandling.js')
  return { rejected, ...failure }
}

describe('sign-out reason parked across the redirect to /login (SEC-9758)', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('parks "displaced" when the refresh answers with the SESSION_DISPLACED error code, and takeSignOutReason reads it once', async () => {
    const { rejected, takeSignOutReason } = await setup(make401('/api/auth/refresh', { error_code: 'SESSION_DISPLACED', message: 'Signed out.' }))

    await expect(rejected(make401('/api/v1/projects/'))).rejects.toBeDefined()

    expect(takeSignOutReason()).toBe('displaced')
    expect(takeSignOutReason()).toBeNull()
  })

  it('parks nothing when the refresh fails for any other reason', async () => {
    const { rejected, takeSignOutReason } = await setup(make401('/api/auth/refresh', { error_code: 'HTTP_ERROR', message: 'Token has been revoked' }))

    await expect(rejected(make401('/api/v1/projects/'))).rejects.toBeDefined()

    expect(takeSignOutReason()).toBeNull()
  })

  it('parks nothing on a network failure of the refresh itself', async () => {
    const { rejected, takeSignOutReason } = await setup(Object.assign(new Error('Network Error'), { isAxiosError: true }))

    await expect(rejected(make401('/api/v1/projects/'))).rejects.toBeDefined()

    expect(takeSignOutReason()).toBeNull()
  })
})
