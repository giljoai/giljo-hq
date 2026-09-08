/**
 * user.rethrow.spec.js (FE-9556)
 *
 * userStore.login() historically swallowed the axios error and returned a
 * bare boolean, which made every caller's status-branched catch block dead
 * code. The contract is now: resolve true on success, THROW the original
 * axios error on failure -- after clearing local user/org state and recording
 * lastLoginErrorStatus (the PR #1002 surface, kept for back-compat).
 * The rethrow cases were proven RED against the pre-fix store (login resolved
 * false instead of throwing).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      login: vi.fn(),
      me: vi.fn(),
    },
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

describe('userStore.login rethrow contract (FE-9556)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('rethrows the original axios error on failure', async () => {
    const store = useUserStore()
    const axiosError = { response: { status: 403, data: { detail: 'nope' } } }
    api.auth.login.mockRejectedValue(axiosError)

    await expect(store.login('sam', 'wrong')).rejects.toBe(axiosError)
  })

  it('clears user state and records lastLoginErrorStatus before rethrowing', async () => {
    const store = useUserStore()
    api.auth.login.mockRejectedValue({ response: { status: 429, data: {} } })

    await expect(store.login('sam', 'wrong')).rejects.toBeTruthy()
    expect(store.currentUser).toBeNull()
    expect(store.lastLoginErrorStatus).toBe(429)
  })

  it('still resolves true and populates the user on success', async () => {
    const store = useUserStore()
    api.auth.login.mockResolvedValue({ data: {} })
    api.auth.me.mockResolvedValue({ data: { id: 'u1', tenant_key: 'tk1' } })

    await expect(store.login('sam', 'right')).resolves.toBe(true)
    expect(store.lastLoginErrorStatus).toBeNull()
  })
})
