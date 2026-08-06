/**
 * Sentry browser SDK initialization for Giljo HQ frontend (INF-5063).
 *
 * **Edition Scope:** SaaS + Demo only. CE MUST NOT call initSentry() with a
 * non-null DSN — the backend setup-status payload returns sentryDsn=null in
 * CE mode, and the bootstrap path in main.js gates on that. This file
 * intentionally uses a runtime dynamic import for `@sentry/vue` so the
 * module evaluates safely even when the package is not installed (CE export
 * pipelines may strip @sentry/vue from package.json).
 *
 * ADR-002: do not read mode here — the caller (main.js) supplies dsn from
 * the setup-status response, which is the authoritative source.
 *
 * Usage:
 *   import { initSentry, setSentryTenantKey } from '@/sentry'
 *   await initSentry(app, { dsn, environment, tenantKey })
 *   // later, after login:
 *   setSentryTenantKey(user.tenant_key)
 */

let _setTag = null // captured @sentry/vue setTag fn after init() — login-refresh path
let _initialized = false

/**
 * Lazy-load ONLY the @sentry/vue named exports we use (FE-9145): init,
 * browserTracingIntegration, setTag. Returns null if the package is not
 * installed (e.g. CE build where the dependency was stripped). Caller MUST
 * handle null.
 *
 * Why named destructuring, not a namespace capture: the previous code did
 * `_sentry = await import('@sentry/vue')` and accessed the whole namespace
 * dynamically across functions. A retained namespace defeats Rollup
 * tree-shaking, so EVERY export was kept in the bundle — including
 * `replayIntegration` and its transitive `rrweb` dependency (~96KB gzip /
 * ~298KB raw, measured), even though Session Replay is intentionally NOT
 * wired. Destructuring the
 * exact three functions used lets the bundler drop the rest. Session Replay
 * is out of scope; re-adding it later is a deliberate change (with privacy
 * masking), not an accidental bundle passenger.
 */
async function loadSentry() {
  try {
    const { init, browserTracingIntegration, setTag } = await import('@sentry/vue')
    return { init, browserTracingIntegration, setTag }
  } catch (error) {
    console.warn('[Sentry] @sentry/vue not available; skipping init:', error?.message || error)
    return null
  }
}

/**
 * Initialize Sentry for the Vue app. No-op if dsn is falsy.
 *
 * @param {object} app - Vue app instance from createApp()
 * @param {object} options
 * @param {string|null} options.dsn - Sentry DSN; null disables Sentry entirely
 * @param {string} options.environment - 'saas' | 'demo' | 'ce' | etc.
 * @param {string|null} options.tenantKey - Tenant key for tag injection
 * @returns {Promise<boolean>} true if initialized, false if skipped
 */
export async function initSentry(app, options = {}) {
  const { dsn, environment, tenantKey } = options
  if (!dsn) {
    // CE / disabled — do not load or init. Zero network calls to Sentry.
    return false
  }

  const Sentry = await loadSentry()
  if (!Sentry) return false

  Sentry.init({
    app,
    dsn,
    environment: environment || 'unknown',
    tracesSampleRate: 0.1,
    sampleRate: 1.0,
    // INF-5070: integrations is the callback form, NOT a static array.
    //
    // @sentry/vue v8+ replaces (does NOT merge) the default integrations
    // when `integrations` is passed as a static array. Shipping
    // `integrations: [browserTracingIntegration()]` therefore dropped
    // globalHandlersIntegration, breadcrumbsIntegration, linkedErrorsIntegration,
    // httpContextIntegration, and the rest. Effect: the SDK kept capturing
    // Vue-tree errors (because passing `app` auto-registers the Vue
    // errorHandler) but stopped capturing window.onerror, unhandled
    // Promise rejections, async user code, third-party script errors, and
    // every other "production-grade" error source. Discovered during the
    // INF-5070 Gate E verification on mcp.example.com.
    //
    // Always extend defaults, never replace.
    integrations: (defaultIntegrations) => [
      ...defaultIntegrations,
      Sentry.browserTracingIntegration(),
    ],
  })

  _initialized = true
  _setTag = Sentry.setTag // retained for the post-login tag-refresh path

  if (tenantKey) {
    Sentry.setTag('tenant_key', tenantKey)
  }

  return true
}

/**
 * Update the tenant_key tag after Sentry has been initialized
 * (e.g. after a user logs in and the tenant key becomes known).
 * No-op if Sentry was never initialized — prevents stray tag calls in CE.
 *
 * @param {string|null} tenantKey
 */
export function setSentryTenantKey(tenantKey) {
  if (!_initialized || !_setTag) return
  if (!tenantKey) return
  _setTag('tenant_key', tenantKey)
}

/**
 * Test helper: reset internal state. Not exported as part of the public API
 * but available for vitest module-reset patterns.
 */
function _resetSentryForTests() {
  _setTag = null
  _initialized = false
}
