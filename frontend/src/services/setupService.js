
import { API_CONFIG } from '@/config/api'
import configService from '@/services/configService'
import { isCeModeValue } from '@/composables/useGiljoMode'

class SetupService {
  constructor() {

    this._statusCache = null
    this._statusCacheTime = 0
    this._statusCacheTTL = 300000
    this._statusPending = null
  }

  getBaseURL() {
    return window.API_BASE_URL || API_CONFIG.REST_API.baseURL
  }

  async checkEnhancedStatus() {
    const now = Date.now()
    if (this._statusCache && now - this._statusCacheTime < this._statusCacheTTL) {
      return this._statusCache
    }

    if (this._statusPending) {
      return this._statusPending
    }

    this._statusPending = this._fetchStatus()
    try {
      const result = await this._statusPending
      return result
    } finally {
      this._statusPending = null
    }
  }

  async _fetchStatus() {
    try {
      const response = await fetch(`${this.getBaseURL()}/api/setup/status`, {
        method: 'GET',
        cache: 'no-cache',
      })

      if (response.ok) {
        const data = await response.json()
        const result = {
          is_fresh_install: data.is_fresh_install,
          total_users_count: data.total_users_count,
          requires_admin_creation: data.requires_admin_creation,
          show_public_landing: data.show_public_landing || false,
          route_signal: data.route_signal,
          mode: data.mode,
          sentryDsn: data.sentryDsn ?? null,
          environment: data.environment,
        }
        this._statusCache = result
        this._statusCacheTime = Date.now()
        return result
      } else {
        console.warn('[SETUP_SERVICE] Setup status transient failure:', response.status)
        return this._transientStatus()
      }
    } catch (error) {
      console.warn('[SETUP_SERVICE] Status check failed:', error)
      return this._fallbackStatus()
    }
  }

  _transientStatus() {
    if (this._statusCache) return this._statusCache
    return {
      ...this._fallbackStatus(),
      is_fresh_install: false,
      requires_admin_creation: false,
      transient_failure: true,
    }
  }

  _fallbackStatus() {
    let mode = 'ce'
    try { mode = configService.getGiljoMode() } catch { /* config not loaded */ }
    const isPublicLandingMode = !isCeModeValue(mode)
    return {
      is_fresh_install: !isPublicLandingMode,
      total_users_count: 0,
      requires_admin_creation: !isPublicLandingMode,
      show_public_landing: isPublicLandingMode,
    }
  }

  invalidateStatusCache() {
    this._statusCache = null
    this._statusCacheTime = 0
  }






  async toggleGit(enabled) {
    const { default: api } = await import('@/services/api')

    try {
      const response = await api.git.toggle(enabled)
      return response.data
    } catch (error) {
      console.error('[SETUP_SERVICE] Git toggle failed:', error)
      throw error
    }
  }

  async getGitSettings() {
    const { default: api } = await import('@/services/api')

    try {
      const response = await api.git.getSettings()
      return response.data
    } catch (error) {
      console.error('[SETUP_SERVICE] Git settings fetch failed:', error)
      throw error
    }
  }

}

export default new SetupService()
