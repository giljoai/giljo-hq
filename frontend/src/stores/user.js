
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api, { setTenantKey } from '@/services/api'
import { setSentryTenantKey } from '@/sentry'
import { useTaskStore } from '@/stores/tasks'

function isIndeterminateAuthError(error) {
  const status = error?.response?.status
  if (status === undefined || status === null) return true
  return status === 429 || status >= 500
}

export const useUserStore = defineStore('user', () => {
  const currentUser = ref(null)

  const lastLoginErrorStatus = ref(null)

  const orgId = ref(null)
  const orgName = ref(null)
  const orgRole = ref(null)

  const isAuthenticated = computed(() => currentUser.value !== null)

  const isAdmin = computed(() => {
    if (!currentUser.value || !currentUser.value.role) {
      return false
    }
    return currentUser.value.role.toLowerCase() === 'admin'
  })

  const currentOrg = computed(() => {
    if (!orgId.value) return null
    return {
      id: orgId.value,
      name: orgName.value,
      role: orgRole.value
    }
  })

  let _fetchPending = null

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

      orgId.value = response.data?.org_id || null
      orgName.value = response.data?.org_name || null
      orgRole.value = response.data?.org_role || null

      if (currentUser.value?.tenant_key) {
        setTenantKey(currentUser.value.tenant_key)
        setSentryTenantKey(currentUser.value.tenant_key)
      }

      return true
    } catch (error) {
      if (currentUser.value && isIndeterminateAuthError(error)) {
        console.warn(
          '[UserStore] Current-user refresh indeterminate, keeping the verified session:',
          error?.response?.status ?? error?.code ?? error?.message,
        )
        _checkAuthAt = 0
        return true
      }

      console.error('[UserStore] Failed to fetch current user:', error)
      currentUser.value = null
      clearOrgFields()
      return false
    }
  }

  async function login(username, password) {
    lastLoginErrorStatus.value = null
    try {
      await api.auth.login(username, password)
      await fetchCurrentUser()
      return true
    } catch (error) {
      console.error('[UserStore] Login failed:', error)
      currentUser.value = null
      clearOrgFields()
      lastLoginErrorStatus.value = error?.response?.status ?? null
      throw error
    }
  }

  async function logout() {
    const outgoingUserId = currentUser.value?.id ?? null
    try {
      await api.auth.logout()
    } catch (error) {
      console.error('[UserStore] Logout endpoint failed:', error)
    } finally {
      currentUser.value = null
      clearOrgFields()

      _fetchPending = null

      _checkAuthAt = 0
      _checkAuthPending = null

      setTenantKey(null)

      try {
        localStorage.removeItem('remembered_username')
      } catch {
        // localStorage may be unavailable in restricted environments
      }

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
        const { useBannerDismissStore } = await import('@/stores/bannerDismissStore')
        useBannerDismissStore().clear(outgoingUserId)
      } catch (e) {
        console.warn('[UserStore] Banner dismissal cleanup skipped:', e)
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

  const CHECK_AUTH_TTL_MS = 5000
  let _checkAuthAt = 0
  let _checkAuthPending = null

  async function checkAuth() {
    if (currentUser.value && Date.now() - _checkAuthAt < CHECK_AUTH_TTL_MS) {
      return true
    }
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

      orgId.value = response.data?.org_id || null
      orgName.value = response.data?.org_name || null
      orgRole.value = response.data?.org_role || null

      if (currentUser.value?.tenant_key) {
        setTenantKey(currentUser.value.tenant_key)
        setSentryTenantKey(currentUser.value.tenant_key)
      }

      _checkAuthAt = Date.now()
      return true
    } catch (error) {
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

      return false
    }
  }

  function clearOrgFields() {
    orgId.value = null
    orgName.value = null
    orgRole.value = null
  }

  async function updateSetupState(payload) {
    const response = await api.auth.updateSetupState(payload)
    const data = response.data
    if (currentUser.value) {
      if (data.setup_complete !== undefined) currentUser.value.setup_complete = data.setup_complete
      if (data.setup_selected_tools !== undefined) currentUser.value.setup_selected_tools = data.setup_selected_tools
      if (data.setup_step_completed !== undefined) currentUser.value.setup_step_completed = data.setup_step_completed
      if (data.learning_complete !== undefined) currentUser.value.learning_complete = data.learning_complete
      if (data.learning_beat !== undefined) currentUser.value.learning_beat = data.learning_beat
      if (data.router_choice !== undefined) currentUser.value.router_choice = data.router_choice
    }
    return data
  }

  function clearUser() {
    currentUser.value = null
    clearOrgFields()
  }

  return {
    currentUser,
    lastLoginErrorStatus,
    orgId,
    orgName,
    orgRole,
    isAuthenticated,
    isAdmin,
    currentOrg,
    fetchCurrentUser,
    login,
    logout,
    checkAuth,
    updateSetupState,
    clearUser,
  }
})
