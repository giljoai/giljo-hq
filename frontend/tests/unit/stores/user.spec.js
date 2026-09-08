/**
 * Unit tests for user store - authentication and role management
 * Following TDD principles: write tests first, then implement
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '@/stores/user'
import api from '@/services/api'

// Mock the API service
vi.mock('@/services/api', () => ({
  default: {
    auth: {
      me: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
    },
  },
  setTenantKey: vi.fn(),
}))

describe('User Store', () => {
  beforeEach(() => {
    // Create a fresh pinia instance for each test
    setActivePinia(createPinia())
    // Clear all mocks before each test
    vi.clearAllMocks()
  })

  describe('State Management', () => {
    it('should initialize with null user and unauthenticated state', () => {
      const store = useUserStore()

      expect(store.currentUser).toBeNull()
      expect(store.isAuthenticated).toBe(false)
    })
  })

  describe('Getters - Role Checking', () => {
    it('should return false for isAdmin when user is null', () => {
      const store = useUserStore()

      expect(store.isAdmin).toBe(false)
    })

    it('should return true for isAdmin when user role is "admin"', () => {
      const store = useUserStore()
      store.currentUser = { username: 'admin', role: 'admin' }

      expect(store.isAdmin).toBe(true)
    })

    it('should return false for isAdmin when user role is "user"', () => {
      const store = useUserStore()
      store.currentUser = { username: 'testuser', role: 'user' }

      expect(store.isAdmin).toBe(false)
    })

    it('should return true for isAuthenticated when user exists', () => {
      const store = useUserStore()
      store.currentUser = { username: 'testuser', role: 'user' }

      expect(store.isAuthenticated).toBe(true)
    })

    it('should handle case-insensitive role checking', () => {
      const store = useUserStore()
      store.currentUser = { username: 'admin', role: 'Admin' }

      expect(store.isAdmin).toBe(true)
    })
  })

  describe('Actions - fetchCurrentUser', () => {
    it('should fetch current user and update state on success', async () => {
      const store = useUserStore()
      const mockUser = {
        id: 1,
        username: 'testuser',
        role: 'user',
        email: 'test@example.com'
      }

      api.auth.me.mockResolvedValue({ data: mockUser })

      await store.fetchCurrentUser()

      expect(store.currentUser).toEqual(mockUser)
      expect(store.isAuthenticated).toBe(true)
      expect(api.auth.me).toHaveBeenCalledTimes(1)
    })

    it('should handle fetch error and set user to null', async () => {
      const store = useUserStore()

      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      await store.fetchCurrentUser()

      expect(store.currentUser).toBeNull()
      expect(store.isAuthenticated).toBe(false)
    })

    it('should deduplicate concurrent calls — only one API request fires', async () => {
      const store = useUserStore()
      const mockUser = { id: 1, username: 'testuser', role: 'user' }

      // Slow response so both calls overlap
      api.auth.me.mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve({ data: mockUser }), 50))
      )

      // Fire two concurrent calls
      const [r1, r2] = await Promise.all([
        store.fetchCurrentUser(),
        store.fetchCurrentUser(),
      ])

      // Both callers get the same result
      expect(r1).toBe(true)
      expect(r2).toBe(true)
      // Only ONE network request was made
      expect(api.auth.me).toHaveBeenCalledTimes(1)
      expect(store.currentUser).toEqual(mockUser)
    })

    it('should allow a new fetch after the previous one completes', async () => {
      const store = useUserStore()
      const mockUser1 = { id: 1, username: 'user1', role: 'user' }
      const mockUser2 = { id: 2, username: 'user2', role: 'admin' }

      api.auth.me
        .mockResolvedValueOnce({ data: mockUser1 })
        .mockResolvedValueOnce({ data: mockUser2 })

      await store.fetchCurrentUser()
      expect(store.currentUser).toEqual(mockUser1)

      await store.fetchCurrentUser()
      expect(store.currentUser).toEqual(mockUser2)
      expect(api.auth.me).toHaveBeenCalledTimes(2)
    })

    it('should clear pending state after a failed fetch so retries work', async () => {
      const store = useUserStore()
      const mockUser = { id: 1, username: 'testuser', role: 'user' }

      api.auth.me
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce({ data: mockUser })

      const r1 = await store.fetchCurrentUser()
      expect(r1).toBe(false)
      expect(store.currentUser).toBeNull()

      // Second call should fire a NEW request, not reuse the failed promise
      const r2 = await store.fetchCurrentUser()
      expect(r2).toBe(true)
      expect(store.currentUser).toEqual(mockUser)
      expect(api.auth.me).toHaveBeenCalledTimes(2)
    })

    it('should propagate failure to all concurrent callers on error', async () => {
      const store = useUserStore()

      api.auth.me.mockImplementation(
        () => new Promise((_, reject) => setTimeout(() => reject(new Error('Server down')), 50))
      )

      const [r1, r2] = await Promise.all([
        store.fetchCurrentUser(),
        store.fetchCurrentUser(),
      ])

      expect(r1).toBe(false)
      expect(r2).toBe(false)
      expect(api.auth.me).toHaveBeenCalledTimes(1)
      expect(store.currentUser).toBeNull()
    })
  })

  describe('Actions - login', () => {
    it('should login user and fetch user data on success', async () => {
      const store = useUserStore()
      const mockUser = { id: 1, username: 'admin', role: 'admin' }

      api.auth.login.mockResolvedValue({ data: { success: true } })
      api.auth.me.mockResolvedValue({ data: mockUser })

      const result = await store.login('admin', 'password123')

      expect(result).toBe(true)
      expect(store.currentUser).toEqual(mockUser)
      expect(api.auth.login).toHaveBeenCalledWith('admin', 'password123')
      expect(api.auth.me).toHaveBeenCalled()
    })

    it('should rethrow on login failure after clearing state', async () => {
      // Re-baselined for FE-9556: login() historically swallowed the axios
      // error into `return false`, which left every caller's status-branched
      // catch block dead. The contract is now: throw the original error after
      // clearing local state (callers own the user-facing copy).
      const store = useUserStore()

      const failure = new Error('Invalid credentials')
      api.auth.login.mockRejectedValue(failure)

      await expect(store.login('admin', 'wrongpassword')).rejects.toBe(failure)
      expect(store.currentUser).toBeNull()
    })
  })

  describe('Actions - logout', () => {
    it('should clear user state and call logout endpoint', async () => {
      const store = useUserStore()
      store.currentUser = { username: 'testuser', role: 'user' }

      api.auth.logout.mockResolvedValue({ data: { success: true } })

      await store.logout()

      expect(store.currentUser).toBeNull()
      expect(store.isAuthenticated).toBe(false)
      expect(api.auth.logout).toHaveBeenCalledTimes(1)
    })

    it('should clear user state even if logout endpoint fails', async () => {
      const store = useUserStore()
      store.currentUser = { username: 'testuser', role: 'user' }

      api.auth.logout.mockRejectedValue(new Error('Network error'))

      await store.logout()

      expect(store.currentUser).toBeNull()
      expect(store.isAuthenticated).toBe(false)
    })

    // Regression tests for route-guard-bypass fix (mcp.example.com 2026-04-24)
    // After logout, NO auth-related reactive state may remain that could
    // cause router.beforeEach to treat the user as authenticated.
    describe('full state reset (route-guard bypass regression)', () => {
      it('should fully clear user, org, and authentication state on logout', async () => {
        const store = useUserStore()
        store.currentUser = {
          id: 'user-1',
          username: 'testuser',
          role: 'admin',
          tenant_key: 'tk-123',
          setup_complete: true,
        }
        store.orgId = 'org-123'
        store.orgName = 'Test Org'
        store.orgRole = 'owner'

        api.auth.logout.mockResolvedValue({ data: { success: true } })

        await store.logout()

        // Every auth-relevant field must be null after logout --
        // nothing the router guard could interpret as "still logged in".
        expect(store.currentUser).toBeNull()
        expect(store.orgId).toBeNull()
        expect(store.orgName).toBeNull()
        expect(store.orgRole).toBeNull()
        expect(store.isAuthenticated).toBe(false)
        expect(store.isAdmin).toBe(false)
        expect(store.currentOrg).toBeNull()
      })

      it('should clear state even if the logout endpoint throws', async () => {
        const store = useUserStore()
        store.currentUser = { id: 'u1', username: 'x', role: 'user' }
        store.orgId = 'org-9'
        store.orgName = 'Nine'
        store.orgRole = 'member'

        api.auth.logout.mockRejectedValue(new Error('Backend down'))

        await store.logout()

        expect(store.currentUser).toBeNull()
        expect(store.orgId).toBeNull()
        expect(store.orgName).toBeNull()
        expect(store.orgRole).toBeNull()
        expect(store.isAuthenticated).toBe(false)
      })

      it('should invalidate the API client tenant key on logout', async () => {
        const { setTenantKey } = await import('@/services/api')
        const store = useUserStore()
        store.currentUser = { id: 'u1', username: 'x', role: 'user', tenant_key: 'tk-xyz' }

        api.auth.logout.mockResolvedValue({ data: { success: true } })

        await store.logout()

        // setTenantKey must be called with null so subsequent requests
        // don't reuse the logged-out user's tenant header.
        expect(setTenantKey).toHaveBeenCalledWith(null)
      })

      it('should clear remembered_username from localStorage on logout', async () => {
        const store = useUserStore()
        store.currentUser = { id: 'u1', username: 'x', role: 'user' }
        api.auth.logout.mockResolvedValue({ data: { success: true } })

        await store.logout()

        expect(window.localStorage.removeItem).toHaveBeenCalledWith('remembered_username')
      })
    })
  })

  describe('Role-based Access Control', () => {
    it('should correctly identify admin users', () => {
      const store = useUserStore()

      // Test admin user
      store.currentUser = { username: 'admin', role: 'admin' }
      expect(store.isAdmin).toBe(true)

      // Test regular user
      store.currentUser = { username: 'user', role: 'user' }
      expect(store.isAdmin).toBe(false)

      // Test no user
      store.currentUser = null
      expect(store.isAdmin).toBe(false)
    })

    it('should handle missing role gracefully', () => {
      const store = useUserStore()
      store.currentUser = { username: 'testuser' }

      expect(store.isAdmin).toBe(false)
      expect(store.isAuthenticated).toBe(true)
    })
  })

  describe('Organization Integration (Handover 0424h)', () => {
    it('should initialize with null org state', () => {
      const store = useUserStore()

      expect(store.orgId).toBeNull()
      expect(store.orgName).toBeNull()
      expect(store.orgRole).toBeNull()
    })

    it('should store org data from API response', async () => {
      const store = useUserStore()
      const mockUser = {
        id: 'user-1',
        username: 'testuser',
        email: 'test@example.com',
        tenant_key: 'tk-123',
        role: 'member',
        org_id: 'org-123',
        org_name: 'Test Organization',
        org_role: 'admin'
      }

      api.auth.me.mockResolvedValue({ data: mockUser })

      await store.fetchCurrentUser()

      expect(store.orgId).toBe('org-123')
      expect(store.orgName).toBe('Test Organization')
      expect(store.orgRole).toBe('admin')
    })

    it('should provide currentOrg computed property', async () => {
      const store = useUserStore()
      const mockUser = {
        id: 'user-1',
        username: 'testuser',
        org_id: 'org-123',
        org_name: 'Test Org',
        org_role: 'member'
      }

      api.auth.me.mockResolvedValue({ data: mockUser })
      await store.fetchCurrentUser()

      const currentOrg = store.currentOrg
      expect(currentOrg).toEqual({
        id: 'org-123',
        name: 'Test Org',
        role: 'member'
      })
    })

    it('should return null for currentOrg when no org data', () => {
      const store = useUserStore()

      expect(store.currentOrg).toBeNull()
    })

    it('should handle missing org data gracefully', async () => {
      const store = useUserStore()
      const mockUser = {
        id: 'user-1',
        username: 'testuser',
        role: 'member'
        // No org_id, org_name, org_role
      }

      api.auth.me.mockResolvedValue({ data: mockUser })
      await store.fetchCurrentUser()

      expect(store.orgId).toBeNull()
      expect(store.orgName).toBeNull()
      expect(store.orgRole).toBeNull()
      expect(store.currentOrg).toBeNull()
    })

    it('should clear org fields on logout', async () => {
      const store = useUserStore()

      // First set org data
      store.orgId = 'org-123'
      store.orgName = 'Test Org'
      store.orgRole = 'admin'
      store.currentUser = { id: 'user-1', username: 'testuser' }

      api.auth.logout.mockResolvedValue({ data: { success: true } })

      await store.logout()

      expect(store.currentUser).toBeNull()
      expect(store.orgId).toBeNull()
      expect(store.orgName).toBeNull()
      expect(store.orgRole).toBeNull()
    })

    it('should clear org fields on login failure', async () => {
      const store = useUserStore()

      // Set initial org state
      store.orgId = 'org-123'
      store.orgName = 'Test Org'
      store.orgRole = 'admin'

      api.auth.login.mockRejectedValue(new Error('Invalid credentials'))

      // FE-9556: login() now rethrows on failure -- org fields must still be
      // cleared before the throw.
      await expect(store.login('user', 'wrong')).rejects.toBeTruthy()

      expect(store.currentUser).toBeNull()
      expect(store.orgId).toBeNull()
      expect(store.orgName).toBeNull()
      expect(store.orgRole).toBeNull()
    })

    it('should clear org fields on fetchCurrentUser failure', async () => {
      const store = useUserStore()

      // Set initial org state
      store.orgId = 'org-123'
      store.orgName = 'Test Org'
      store.orgRole = 'admin'

      api.auth.me.mockRejectedValue(new Error('Unauthorized'))

      const result = await store.fetchCurrentUser()

      expect(result).toBe(false)
      expect(store.currentUser).toBeNull()
      expect(store.orgId).toBeNull()
      expect(store.orgName).toBeNull()
      expect(store.orgRole).toBeNull()
    })

    it('should clear org fields on checkAuth failure', async () => {
      const store = useUserStore()

      // Set initial org state
      store.orgId = 'org-123'
      store.orgName = 'Test Org'
      store.orgRole = 'admin'

      api.auth.me.mockRejectedValue(new Error('Session expired'))

      const result = await store.checkAuth()

      expect(result).toBe(false)
      expect(store.currentUser).toBeNull()
      expect(store.orgId).toBeNull()
      expect(store.orgName).toBeNull()
      expect(store.orgRole).toBeNull()
    })

    it('should provide clearUser() method', () => {
      const store = useUserStore()

      // Set user and org data
      store.currentUser = { id: 'user-1', username: 'testuser' }
      store.orgId = 'org-123'
      store.orgName = 'Test Org'
      store.orgRole = 'admin'

      // Call clearUser
      store.clearUser()

      expect(store.currentUser).toBeNull()
      expect(store.orgId).toBeNull()
      expect(store.orgName).toBeNull()
      expect(store.orgRole).toBeNull()
    })

    it('should update org fields on checkAuth success', async () => {
      const store = useUserStore()
      const mockUser = {
        id: 'user-1',
        username: 'testuser',
        tenant_key: 'tk-123',
        role: 'member',
        org_id: 'org-456',
        org_name: 'New Organization',
        org_role: 'owner'
      }

      api.auth.me.mockResolvedValue({ data: mockUser })

      const result = await store.checkAuth()

      expect(result).toBe(true)
      expect(store.orgId).toBe('org-456')
      expect(store.orgName).toBe('New Organization')
      expect(store.orgRole).toBe('owner')
    })
  })

  // perf-findings 2026-06-11: the router guard calls checkAuth() on every
  // navigation. A short TTL + in-flight dedup collapses bursts so rapid
  // navigation doesn't fire one /api/auth/me each (rate-limit bucket pressure).
  describe('Actions - checkAuth TTL + in-flight dedup', () => {
    const okUser = { data: { id: 'u1', username: 'a', tenant_key: 'tk' } }

    it('collapses concurrent checkAuth() calls into ONE /api/auth/me request', async () => {
      const store = useUserStore()
      api.auth.me.mockResolvedValue(okUser)

      const results = await Promise.all([store.checkAuth(), store.checkAuth(), store.checkAuth()])

      expect(results).toEqual([true, true, true])
      expect(api.auth.me).toHaveBeenCalledTimes(1)
    })

    it('serves a recent success from the TTL cache without re-hitting the network', async () => {
      const store = useUserStore()
      api.auth.me.mockResolvedValue(okUser)

      await store.checkAuth()
      await store.checkAuth() // within TTL → cached, no second call

      expect(api.auth.me).toHaveBeenCalledTimes(1)
    })

    it('re-validates after the TTL window expires', async () => {
      vi.useFakeTimers()
      try {
        const store = useUserStore()
        api.auth.me.mockResolvedValue(okUser)

        await store.checkAuth()
        expect(api.auth.me).toHaveBeenCalledTimes(1)

        vi.advanceTimersByTime(6000) // > CHECK_AUTH_TTL_MS (5000)
        await store.checkAuth()
        expect(api.auth.me).toHaveBeenCalledTimes(2)
      } finally {
        vi.useRealTimers()
      }
    })

    it('does not cache failures — a failed check re-hits on the next call', async () => {
      const store = useUserStore()
      api.auth.me.mockRejectedValueOnce(new Error('401'))

      expect(await store.checkAuth()).toBe(false)

      api.auth.me.mockResolvedValueOnce(okUser)
      expect(await store.checkAuth()).toBe(true)
      expect(api.auth.me).toHaveBeenCalledTimes(2)
    })
  })
})
