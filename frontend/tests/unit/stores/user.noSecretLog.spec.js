/**
 * A failed sign-in must not write the typed password to the console:
 * the axios error carries the request body in config.data.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/api', () => ({
  default: {
    auth: { login: vi.fn(), me: vi.fn() },
    tasks: { list: vi.fn() },
  },
  apiClient: {},
  setTenantKey: vi.fn(),
}))

vi.mock('@/sentry', () => ({
  setSentryTenantKey: vi.fn(),
}))

import api from '@/services/api'
import { useUserStore } from '@/stores/user'

const SECRET_PASSWORD = 'Unrelated-Passphrase-77'

describe('userStore.login -- a failure logs no password', () => {
  let errorSpy

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    errorSpy.mockRestore()
  })

  it('logs the status, not the axios error with its request body', async () => {
    const err = new Error('Request failed with status code 401')
    err.config = { data: JSON.stringify({ username: 'sam', password: SECRET_PASSWORD }) }
    err.response = { status: 401, data: {} }
    api.auth.login.mockRejectedValue(err)

    await expect(useUserStore().login('sam', SECRET_PASSWORD)).rejects.toBe(err)

    const logged = errorSpy.mock.calls
      .flat()
      .map((arg) =>
        arg instanceof Error
          ? `${arg.message} ${JSON.stringify(arg.config ?? {})}`
          : JSON.stringify(arg),
      )
      .join('\n')
    expect(errorSpy).toHaveBeenCalled()
    expect(logged).not.toContain(SECRET_PASSWORD)
  })
})
