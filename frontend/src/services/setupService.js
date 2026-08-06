/**
 * Setup Wizard API Service
 *
 * Handles all API communication for the setup wizard including:
 * - Tool detection
 * - MCP configuration generation
 * - Database testing
 * - System setup
 * - Setup completion
 */

import { API_CONFIG } from '@/config/api'
import configService from '@/services/configService'

class SetupService {
  constructor() {
    // IMPORTANT: Don't cache baseURL at construction time
    // Read it dynamically from window.API_BASE_URL or API_CONFIG at call time

    // Cache for setup status. The router guard (authGuard.js) AWAITS this on
    // EVERY navigation, so a slow /api/setup/status (e.g. Cloudflare tunnel
    // jitter — backend handler is ~6ms, the latency is the network) BLOCKS the
    // page transition and is felt as a navigation "hang" (perf-findings
    // 2026-06-11). A 2s TTL meant any nav >2s after the last re-fetched through
    // that jittery hop (~22×/5min during normal clicking). The status is
    // near-static — it only changes on admin-account creation, which calls
    // invalidateStatusCache() (CreateAdminAccount.vue) — so a long TTL is safe
    // and eliminates ~95% of these blocking calls. In-flight dedup still covers
    // same-burst concurrency.
    this._statusCache = null
    this._statusCacheTime = 0
    this._statusCacheTTL = 300000 // 5 minutes — status is near-static; the one
    // routing-critical transition (admin creation) explicitly invalidates.
    this._statusPending = null // Deduplicates concurrent in-flight requests
  }

  /**
   * Get the current API base URL (runtime-aware)
   * @returns {string}
   */
  getBaseURL() {
    return window.API_BASE_URL || API_CONFIG.REST_API.baseURL
  }

  /**
   * Check fresh install status (Handover 0034 - simplified)
   * @returns {Promise<{is_fresh_install: boolean, total_users_count: number, requires_admin_creation: boolean}>}
   */
  async checkEnhancedStatus() {
    // Return cached result if within TTL
    const now = Date.now()
    if (this._statusCache && now - this._statusCacheTime < this._statusCacheTTL) {
      return this._statusCache
    }

    // If a request is already in-flight, reuse it (deduplicates concurrent calls)
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
          // INF-5063: Sentry telemetry config. Backend returns sentryDsn=null
          // for CE; non-null only in saas/demo with telemetry configured.
          // main.js reads these to gate the Sentry init call.
          sentryDsn: data.sentryDsn ?? null,
          environment: data.environment,
        }
        this._statusCache = result
        this._statusCacheTime = Date.now()
        return result
      } else {
        // FE-9233: an HTTP response means the server is ALIVE, so a 429 (rate
        // limited) or 5xx is TRANSIENT -- not "this box is unconfigured".
        // Falling through to _fallbackStatus() here returned is_fresh_install:
        // true in CE, which authGuard.js PRIORITY 1 turned into a reroute to
        // the /welcome CreateAdminAccount wizard on a fully set-up install.
        console.warn('[SETUP_SERVICE] Setup status transient failure:', response.status)
        return this._transientStatus()
      }
    } catch (error) {
      console.warn('[SETUP_SERVICE] Status check failed:', error)
      return this._fallbackStatus()
    }
  }

  /**
   * FE-9233: result for a TRANSIENT failure -- the server answered (429/5xx),
   * so it exists and is configured-or-not in a way we simply could not read
   * this time. Never asserts a fresh install.
   *
   * Prefers the last-known good status even if its TTL has expired: a stale
   * true answer beats a fresh guess. Deliberately NOT written to _statusCache,
   * so the next call retries the network instead of serving this shape for the
   * full TTL.
   *
   * Derived from _fallbackStatus() so mode-specific semantics (saas/demo
   * public-landing) stay identical; the ONLY thing stripped is the CE
   * fresh-install assertion that caused the misroute.
   */
  _transientStatus() {
    if (this._statusCache) return this._statusCache
    return {
      ...this._fallbackStatus(),
      is_fresh_install: false,
      requires_admin_creation: false,
      transient_failure: true,
    }
  }

  /**
   * Mode-aware fallback when /api/setup/status is unreachable.
   *
   * FE-9233 -- LOAD-BEARING, do not repurpose: this is reached only from the
   * catch branch of _fetchStatus(), i.e. a genuine connection failure with
   * nothing listening. That is the CE installer first-boot path (the frontend
   * comes up before the backend finishes booting) and the CE fresh-install
   * default here is what carries a real first-boot user into the
   * admin-creation wizard. Transient HTTP failures go to _transientStatus().
   *
   * In demo/saas mode we must NEVER default to is_fresh_install: true --
   * that would race an anonymous visitor into the CE CreateAdminAccount
   * wizard during a transient network error. Instead fall back to
   * "public landing" semantics.
   */
  _fallbackStatus() {
    let mode = 'ce'
    try { mode = configService.getGiljoMode() } catch { /* config not loaded */ }
    // eslint-disable-next-line giljo-internal/no-scattered-mode-checks -- service class fallback; non-component context cannot use Vue composable; intentional raw mode check
    const isPublicLandingMode = mode !== 'ce'
    return {
      is_fresh_install: !isPublicLandingMode,
      total_users_count: 0,
      requires_admin_creation: !isPublicLandingMode,
      show_public_landing: isPublicLandingMode,
    }
  }

  /**
   * Invalidate the setup status cache (call after admin account creation)
   */
  invalidateStatusCache() {
    this._statusCache = null
    this._statusCacheTime = 0
  }

  /**
   * Check setup completion status (Handover 0034 - backward compatibility wrapper)
   * @returns {Promise<{requires_setup: boolean, is_fresh_install: boolean}>}
   */
  async checkStatus() {
    try {
      const status = await this.checkEnhancedStatus()
      return {
        requires_setup: false, // v3.0: Always false, no setup wizard
        is_fresh_install: status.is_fresh_install,
      }
    } catch (error) {
      console.warn('[SETUP_SERVICE] Status check failed:', error)
      // Fallback - no setup required, not fresh install
      return { requires_setup: false, is_fresh_install: false }
    }
  }

  // AUTO-INJECTION METHODS REMOVED (v3.0 unified architecture)
  // registerMcp() and checkMcpConfigured() removed
  // Use downloadable setup scripts instead for all users (localhost and remote)

  // LAN/network configuration removed for v3.0 unified architecture

  // Network adapters detection removed for v3.0 unified architecture

  // =========================================================================
  // API wrapper methods (Serena, Git)
  //
  // These methods use dynamic import('@/services/api') to avoid a circular
  // dependency: api.js imports setupService for fresh-install detection,
  // so setupService cannot statically import api. The wrappers also add
  // [SETUP_SERVICE] log prefixes for filtered debugging and re-throw so
  // callers retain normal error handling. Do NOT collapse these into
  // direct api calls at the call sites -- the circular dependency will
  // break the build.
  // =========================================================================

  /**
   * Toggle Serena MCP prompt injection on/off
   * @param {boolean} enabled - Whether to enable Serena prompts
   * @returns {Promise<{success: boolean, enabled: boolean, message?: string}>}
   */
  async toggleSerena(enabled) {
    // Import API here to avoid circular dependency
    const { default: api } = await import('@/services/api')

    try {
      const response = await api.serena.toggle(enabled)
      return response.data
    } catch (error) {
      console.error('[SETUP_SERVICE] Serena toggle failed:', error)
      throw error
    }
  }

  /**
   * Get current Serena MCP prompt injection status
   * @returns {Promise<{enabled: boolean}>}
   */
  async getSerenaStatus() {
    // Import API here to avoid circular dependency
    const { default: api } = await import('@/services/api')

    try {
      const response = await api.serena.getStatus()
      return response.data
    } catch (error) {
      console.error('[SETUP_SERVICE] Serena status check failed:', error)
      throw error
    }
  }

  // Admin user creation removed for v3.0 unified architecture

  /**
   * Toggle Git integration on/off (system-level)
   * @param {boolean} enabled - Whether to enable Git integration
   * @returns {Promise<{success: boolean, enabled: boolean, message?: string, settings?: object}>}
   */
  async toggleGit(enabled) {
    // Import API here to avoid circular dependency
    const { default: api } = await import('@/services/api')

    try {
      const response = await api.git.toggle(enabled)
      return response.data
    } catch (error) {
      console.error('[SETUP_SERVICE] Git toggle failed:', error)
      throw error
    }
  }

  /**
   * Get current Git integration settings
   * @returns {Promise<{enabled: boolean, use_in_prompts: boolean, include_commit_history: boolean, max_commits: number, branch_strategy: string}>}
   */
  async getGitSettings() {
    // Import API here to avoid circular dependency
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
