/**
 * FE-0069 PR A: a wrong current password on the change-password screen is ONE send.
 *
 * Uses the REAL api.js and the REAL accounts.js; only the network adapter is replaced,
 * and it records every send. The refresh endpoint answers 200 because the screen is
 * only reachable with a live session.
 *
 * The answer the server gives for a wrong current password is pinned in ONE place,
 * fixtures/change_password_wrong_current.json. The route test
 * (tests/api/test_sec0064_current_password_guess_limit.py, test_wrong_current_password_answers_400_...)
 * asserts the real route answers with exactly that status, error_code and message,
 * so this spec and the route cannot drift apart silently.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import axios from 'axios'
import wrongCurrent from './fixtures/change_password_wrong_current.json'

vi.unmock('@/services/api')

vi.mock('@/router', () => {
  const resolve = vi.fn((path) => ({ path: String(path).split('?')[0], meta: { requiresAuth: true } }))
  return { default: { resolve, push: vi.fn(), currentRoute: { value: { meta: {} } } } }
})

vi.mock('@/services/setupService', () => ({
  default: { checkEnhancedStatus: vi.fn(() => Promise.resolve({ is_fresh_install: false })) },
}))

function rejectWith(config, status, data) {
  return Promise.reject(
    new axios.AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', config, null, {
      status,
      statusText: '',
      data,
      headers: {},
      config,
    }),
  )
}

async function setup(answer) {
  Object.defineProperty(window, 'location', {
    writable: true,
    configurable: true,
    value: { pathname: '/account/profile', search: '' },
  })
  vi.resetModules()
  const { api, apiClient } = await import('@/services/api')
  const sends = []
  apiClient.defaults.adapter = (config) => {
    const url = String(config.url)
    sends.push(url)
    if (url.includes('/api/auth/refresh')) {
      return Promise.resolve({ data: {}, status: 200, statusText: 'OK', headers: {}, config })
    }
    return rejectWith(config, answer.status, {
      error_code: answer.error_code,
      message: answer.message,
      context: {},
      status_code: answer.status,
    })
  }
  return { api, sends }
}

const count = (sends, part) => sends.filter((s) => s.includes(part)).length

describe('change password: a wrong current password is one send', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('the answer the route gives now (400) is sent once, with no refresh', async () => {
    const { api, sends } = await setup(wrongCurrent)
    const err = await api.auth
      .changePassword('U1', { old_password: 'wrong', new_password: 'NewPassw0rd!x' })
      .catch((e) => e)

    expect(err.response.status).toBe(400)
    expect(count(sends, '/api/v1/users/U1/password')).toBe(1)
    expect(count(sends, '/api/auth/refresh')).toBe(0)
  })

  it('the old answer (401 AuthenticationError) was sent twice: the incident', async () => {
    const { api, sends } = await setup({
      status: 401,
      error_code: 'AUTHENTICATIONERROR',
      message: 'Current password is incorrect',
    })
    await api.auth.changePassword('U1', { old_password: 'wrong', new_password: 'NewPassw0rd!x' }).catch((e) => e)

    expect(count(sends, '/api/v1/users/U1/password')).toBe(2)
    expect(count(sends, '/api/auth/refresh')).toBe(1)
  })
})
