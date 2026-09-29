/**
 * api.js act-first gate reaction (BE-9698).
 *
 * The server now returns 403 PASSWORD_CHANGE_REQUIRED / TERMS_REACCEPTANCE_REQUIRED
 * from any authenticated route while one of those steps is pending (backend:
 * giljo_mcp.auth.dependencies.act_first_gate_violation). The SPA reaction is a
 * few lines in the existing response interceptor, the same shape as the
 * existing 401 -> /login redirect: route to the screen that completes the
 * pending step instead of leaving the caller with a bare 403.
 *
 * Strategy mirrors tests/services/api.refresh-single-flight.spec.js: import the
 * real module fresh, grab the registered response-error handler, and invoke it
 * directly with a fabricated 403 -- no network touched.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.unmock('@/services/api')

vi.mock('@/router', () => ({
  default: {
    resolve: vi.fn(() => ({ meta: {} })),
    push: vi.fn(),
    currentRoute: { value: { meta: {} } },
  },
}))

function mockLocation(path) {
  Object.defineProperty(window, 'location', {
    writable: true,
    configurable: true,
    value: { pathname: path, search: '' },
  })
}

function makeGateError(errorCode, url = '/api/v1/users/me/field-priority') {
  return Object.assign(new Error(`Request failed with status code 403`), {
    isAxiosError: true,
    config: { url, method: 'get', headers: {} },
    response: {
      status: 403,
      data: { error_code: errorCode, message: 'gated', context: {}, timestamp: '2026-09-28T00:00:00Z' },
      headers: {},
    },
  })
}

async function setup() {
  mockLocation('/home')
  vi.resetModules()
  const apiModule = await import('@/services/api.js')
  const handlers = apiModule.apiClient.interceptors.response.handlers.filter(Boolean)
  const { rejected } = handlers[handlers.length - 1]
  const router = (await import('@/router')).default
  return { rejected, router }
}

describe('api.js act-first gate reaction (BE-9698)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('routes to /first-login on PASSWORD_CHANGE_REQUIRED', async () => {
    const { rejected, router } = await setup()

    await rejected(makeGateError('PASSWORD_CHANGE_REQUIRED')).catch(() => {})

    expect(router.push).toHaveBeenCalledWith('/first-login')
  })

  it('routes to /reaccept-terms on TERMS_REACCEPTANCE_REQUIRED', async () => {
    const { rejected, router } = await setup()

    await rejected(makeGateError('TERMS_REACCEPTANCE_REQUIRED')).catch(() => {})

    expect(router.push).toHaveBeenCalledWith('/reaccept-terms')
  })

  it('an ordinary 403 (no gate code) never redirects', async () => {
    const { rejected, router } = await setup()

    await rejected(makeGateError('AUTHORIZATIONERROR')).catch(() => {})

    expect(router.push).not.toHaveBeenCalled()
  })

  it('the rejection still propagates to the caller (no swallowed error)', async () => {
    const { rejected } = await setup()

    await expect(rejected(makeGateError('PASSWORD_CHANGE_REQUIRED'))).rejects.toBeTruthy()
  })

  it('does not redirect a second time for a request already on the gate screen', async () => {
    mockLocation('/first-login')
    vi.resetModules()
    const apiModule = await import('@/services/api.js')
    const handlers = apiModule.apiClient.interceptors.response.handlers.filter(Boolean)
    const { rejected } = handlers[handlers.length - 1]
    const router = (await import('@/router')).default

    await rejected(makeGateError('PASSWORD_CHANGE_REQUIRED')).catch(() => {})

    expect(router.push).not.toHaveBeenCalled()
  })
})
