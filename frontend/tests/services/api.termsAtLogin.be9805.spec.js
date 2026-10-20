/**
 * BE-9805: the server decides Terms when a session is minted and answers a session
 * below the current Terms version with 401 TERMS_REACCEPTANCE_REQUIRED. No refresh
 * can fix that, so the interceptor routes straight to the Terms screen. A session
 * minted before the claim existed answers 401 SESSION_REFRESH_REQUIRED, which the
 * ordinary silent refresh fixes without signing anyone out.
 *
 * Same strategy as api.signOutReason.sec9758.spec.js: real module, fake adapter,
 * the registered response-error handler driven with a fabricated error.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.unmock('@/services/api')

const push = vi.fn()
vi.mock('@/router', () => {
  const resolve = vi.fn((path) => {
    const normalized = String(path).split('?')[0]
    return { path: normalized, meta: { requiresAuth: normalized !== '/login' } }
  })
  return { default: { resolve, push, currentRoute: { value: { meta: {} } } } }
})

vi.mock('@/services/setupService', () => ({
  default: { checkEnhancedStatus: vi.fn(() => Promise.resolve({ is_fresh_install: false })) },
}))

function makeError(status, url, data) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    config: { url, method: 'get', headers: {} },
    response: { status, data, headers: {} },
  })
}

async function setup() {
  Object.defineProperty(window, 'location', {
    writable: true,
    configurable: true,
    value: { pathname: '/home', search: '' },
  })
  vi.resetModules()
  const { apiClient } = await import('@/services/api.js')
  const adapter = vi.fn((config) =>
    Promise.resolve({ data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config }),
  )
  apiClient.defaults.adapter = adapter
  const handlers = apiClient.interceptors.response.handlers.filter(Boolean)
  const { rejected } = handlers[handlers.length - 1]
  return { rejected, adapter }
}

const refreshCalls = (adapter) =>
  adapter.mock.calls.filter(([config]) => String(config.url).includes('/api/auth/refresh'))

describe('Terms decided at sign-in (BE-9805)', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('routes a 401 TERMS_REACCEPTANCE_REQUIRED to the Terms screen without a refresh', async () => {
    const { rejected, adapter } = await setup()

    await expect(
      rejected(makeError(401, '/api/v1/projects/', { error_code: 'TERMS_REACCEPTANCE_REQUIRED' })),
    ).rejects.toBeDefined()

    expect(push).toHaveBeenCalledWith('/reaccept-terms')
    expect(refreshCalls(adapter)).toHaveLength(0)
  })

  it('silently refreshes and retries a 401 SESSION_REFRESH_REQUIRED (deploy day, no sign-out)', async () => {
    const { rejected, adapter } = await setup()

    const retried = await rejected(
      makeError(401, '/api/v1/projects/', { error_code: 'SESSION_REFRESH_REQUIRED' }),
    )

    expect(refreshCalls(adapter)).toHaveLength(1)
    expect(retried.status).toBe(200)
    expect(push).not.toHaveBeenCalled()
  })

  it('still routes a 403 PASSWORD_CHANGE_REQUIRED to the password screen', async () => {
    const { rejected } = await setup()

    await expect(
      rejected(makeError(403, '/api/v1/projects/', { error_code: 'PASSWORD_CHANGE_REQUIRED' })),
    ).rejects.toBeDefined()

    expect(push).toHaveBeenCalledWith('/first-login')
  })
})
