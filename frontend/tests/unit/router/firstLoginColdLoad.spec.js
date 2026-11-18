import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '@/stores/user'
import { createAuthGuard } from '@/router/authGuard'
import { routes } from '@/router'

vi.mock('@/services/api', () => ({
  default: { auth: { me: vi.fn(), login: vi.fn(), logout: vi.fn() } },
}))

import api from '@/services/api'

describe('/first-login on a cold page load (real route meta, empty store)', () => {
  let guard
  let next
  let to

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    const setupService = {
      checkEnhancedStatus: vi.fn().mockResolvedValue({
        is_fresh_install: false,
        total_users_count: 2,
        route_signal: 'public_landing',
        mode: 'saas',
      }),
    }
    guard = createAuthGuard({ setupService, configService: { getGiljoMode: () => 'saas' } })
    next = vi.fn()
    const route = routes.find((r) => r.path === '/first-login')
    to = { path: '/first-login', fullPath: '/first-login', meta: route.meta }
  })

  it('keeps a signed-in person on the page', async () => {
    expect(useUserStore().currentUser).toBeNull()
    api.auth.me.mockResolvedValue({ data: { id: 1, username: 'u', role: 'admin' } })
    await guard(to, { path: '/', fullPath: '/', matched: [] }, next)
    expect(api.auth.me).toHaveBeenCalledTimes(1)
    expect(next).toHaveBeenCalledWith()
  })

  it('sends a signed-out visitor to /landing, as before', async () => {
    api.auth.me.mockRejectedValue({ response: { status: 401 } })
    await guard(to, { path: '/', fullPath: '/', matched: [] }, next)
    expect(next).toHaveBeenCalledWith('/landing')
  })
})
