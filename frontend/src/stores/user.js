/**
 * User Store - Authentication and Role Management
 * Manages user authentication state and role-based access control
 * Includes organization context (Handover 0424h)
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api, { setTenantKey } from '@/services/api'
import { setSentryTenantKey } from '@/sentry'
import { useTaskStore } from '@/stores/tasks'  // FE-9151: static (was a dynamic import); usage stays function-level

export const useUserStore = defineStore('user', () => {
  // State
  const currentUser = ref(null)

  // Org state (Handover 0424h)
  const orgId = ref(null)
  const orgName = ref(null)
  const orgRole = ref(null)

  // Getters
  const isAuthenticated = computed(() => currentUser.value !== null)

  const isAdmin = computed(() => {
    if (!currentUser.value || !currentUser.value.role) {
      return false
    }
    return currentUser.value.role.toLowerCase() === 'admin'
  })

  // Organization computed properties (Handover 0424h)
  const currentOrg = computed(() => {
    if (!orgId.value) return null
    return {
      id: orgId.value,
      name: orgName.value,
      role: orgRole.value
    }
  })

  // Deduplicates concurrent fetchCurrentUser() calls (single in-flight request)
  let _fetchPending = null

  // Actions
  async function fetchCurrentUser() {
    if (_fetchPending) return _fetchPending
    _fetchPending = _doFetchCurrentUser()
    try {
      return await _fetchPending
    } finally {
      _fetchPending = null
    }
  }

  async function _doFetchCurrentUser() {
    try {
      const response = await api.auth.me()
      currentUser.value = response.data

      // Store org fields from API response (Handover 0424h)
      orgId.value = response.data?.org_id || null
      orgName.value = response.data?.org_name || null
      orgRole.value = response.data?.org_role || null

      // Update API client tenant key after successful auth
      if (currentUser.value?.tenant_key) {
        setTenantKey(currentUser.value.tenant_key)
        // INF-5063: refresh Sentry tenant_key tag (no-op when Sentry inactive).
        setSentryTenantKey(currentUser.value.tenant_key)
      }

      return true
    } catch (error) {
      console.error('[UserStore] Failed to fetch current user:', error)
      currentUser.value = null
      clearOrgFields()
      return false
    }
  }

  async function login(username, password) {
    try {
      await api.auth.login(username, password)
      // After successful login, fetch the user data
      await fetchCurrentUser()
      return true
    } catch (error) {
      console.error('[UserStore] Login failed:', error)
      currentUser.value = null
      clearOrgFields()
      return false
    }
  }

  async function logout() {
    // FE-9241: capture the outgoing user's id before it's nulled below —
    // notificationStore.clearAll() needs it to clear that user's localStorage-
    // persisted `_local` notification rows (silent-agent bell notifications
    // that never reach the DB), so a different account on the same browser
    // can't rehydrate the previous user's notifications.
    const outgoingUserId = currentUser.value?.id ?? null
    try {
      await api.auth.logout()
    } catch (error) {
      console.error('[UserStore] Logout endpoint failed:', error)
      // Continue with local cleanup even if API call fails
    } finally {
      // Always clear local auth state -- every field the router guard or any
      // view could read must be reset so a post-logout navigation cannot
      // render a protected view from stale Pinia state (regression: demo
      // server 2026-04-24, route-guard-bypass leak).
      currentUser.value = null
      clearOrgFields()

      // Cancel any in-flight fetchCurrentUser() dedupe token so the next
      // navigation fires a fresh /api/auth/me against the now-invalid cookie.
      _fetchPending = null

      // Invalidate the checkAuth() TTL + in-flight token so the next router
      // guard does a fresh check against the now-invalid cookie (no stale pass).
      _checkAuthAt = 0
      _checkAuthPending = null

      // Clear tenant key from API client so subsequent pre-auth requests
      // (e.g. /api/setup/status) don't reuse the logged-out user's header.
      setTenantKey(null)

      // Clear remember me data
      try {
        localStorage.removeItem('remembered_username')
      } catch {
        // localStorage may be unavailable in restricted environments
      }

      // Clear dependent stores on logout (tenant isolation defense-in-depth).
      // Wrap dynamic imports in try/catch so a bundler or test-env failure
      // here can never prevent the auth state above from being cleared.
      try {
        const { useWebSocketStore } = await import('@/stores/websocket')
        useWebSocketStore().disconnect()
      } catch (e) {
        console.warn('[UserStore] WebSocket disconnect skipped:', e)
      }
      try {
        const { useNotificationStore } = await import('@/stores/notifications')
        useNotificationStore().clearAll(outgoingUserId)
      } catch (e) {
        console.warn('[UserStore] Notification store cleanup skipped:', e)
      }
      try {
        const { useProductStore } = await import('@/stores/products')
        useProductStore().clearProductData()
      } catch (e) {
        console.warn('[UserStore] Product store cleanup skipped:', e)
      }
      try {
        useTaskStore().tasks = []
      } catch (e) {
        console.warn('[UserStore] Task store cleanup skipped:', e)
      }
    }
  }

  // checkAuth() is called by the router guard on EVERY navigation. Without
  // throttling, rapid clicks fire one /api/auth/me per navigation, piling onto
  // rate-limit bucket pressure (perf-findings 2026-06-11). A short TTL collapses
  // bursts and an in-flight dedup collapses concurrent callers. This only
  // affects the client-side route gate — the backend still enforces auth on
  // every API call, so a few seconds of staleness is never a security boundary.
  const CHECK_AUTH_TTL_MS = 5000
  let _checkAuthAt = 0
  let _checkAuthPending = null

  async function checkAuth() {
    // Serve a very recent successful result without re-hitting the network.
    if (currentUser.value && Date.now() - _checkAuthAt < CHECK_AUTH_TTL_MS) {
      return true
    }
    // Collapse concurrent callers onto a single in-flight request.
    if (_checkAuthPending) return _checkAuthPending
    _checkAuthPending = _doCheckAuth()
    try {
      return await _checkAuthPending
    } finally {
      _checkAuthPending = null
    }
  }

  async function _doCheckAuth() {
    try {
      const response = await api.auth.me()
      currentUser.value = response.data

      // Store org fields from API response (Handover 0424h)
      orgId.value = response.data?.org_id || null
      orgName.value = response.data?.org_name || null
      orgRole.value = response.data?.org_role || null

      // Update API client tenant key after successful auth
      if (currentUser.value?.tenant_key) {
        setTenantKey(currentUser.value.tenant_key)
        // INF-5063: refresh Sentry tenant_key tag (no-op when Sentry inactive).
        setSentryTenantKey(currentUser.value.tenant_key)
      }

      _checkAuthAt = Date.now()
      return true
    } catch (error) {
      // FE-9233: a 429 (rate limited) or 5xx is the server saying "not now",
      // NOT "you are logged out". Clearing the session on those threw a
      // throttled user out to /login mid-session. Keep the last-known auth
      // state and let the next navigation re-verify -- _checkAuthAt is left
      // at 0 so nothing is served stale from the TTL.
      //
      // Not an auth relaxation: we only preserve an already-successful
      // check, never fabricate one, and the backend still enforces auth on
      // every API call (see the CHECK_AUTH_TTL_MS note above) -- this client
      // gate has never been the security boundary.
      const status = error?.response?.status
      if (status === 429 || status >= 500) {
        console.warn('[UserStore] Auth check transient failure:', status)
        _checkAuthAt = 0
        return !!currentUser.value
      }

      console.error('[UserStore] Auth check failed:', error)
      currentUser.value = null
      clearOrgFields()
      _checkAuthAt = 0

      // v3.0 Unified: Always require valid authentication
      // No localhost bypass - unified authentication for ALL IPs
      return false
    }
  }

  // Helper method to clear org fields (Handover 0424h)
  function clearOrgFields() {
    orgId.value = null
    orgName.value = null
    orgRole.value = null
  }

  // Update setup wizard state (Handover 0855c)
  async function updateSetupState(payload) {
    const response = await api.auth.updateSetupState(payload)
    const data = response.data
    if (currentUser.value) {
      if (data.setup_complete !== undefined) currentUser.value.setup_complete = data.setup_complete
      if (data.setup_selected_tools !== undefined) currentUser.value.setup_selected_tools = data.setup_selected_tools
      if (data.setup_step_completed !== undefined) currentUser.value.setup_step_completed = data.setup_step_completed
      if (data.learning_complete !== undefined) currentUser.value.learning_complete = data.learning_complete
      // FE-9200 seam: tutorial resume fields (BE-9201 schema, in flight).
      // Absent from the response until the backend ships them — tolerated.
      if (data.learning_beat !== undefined) currentUser.value.learning_beat = data.learning_beat
      if (data.router_choice !== undefined) currentUser.value.router_choice = data.router_choice
    }
    return data
  }

  // Clear all user and org state (Handover 0424h)
  function clearUser() {
    currentUser.value = null
    clearOrgFields()
  }

  return {
    // State
    currentUser,
    // Org state (Handover 0424h)
    orgId,
    orgName,
    orgRole,
    // Getters
    isAuthenticated,
    isAdmin,
    // Org computed properties (Handover 0424h)
    currentOrg,
    // Actions
    fetchCurrentUser,
    login,
    logout,
    checkAuth,
    updateSetupState,
    clearUser,
  }
})
