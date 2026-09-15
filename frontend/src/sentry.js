
let _setTag = null
let _initialized = false

async function loadSentry() {
  try {
    const { init, browserTracingIntegration, setTag } = await import('@sentry/vue')
    return { init, browserTracingIntegration, setTag }
  } catch (error) {
    console.warn('[Sentry] @sentry/vue not available; skipping init:', error?.message || error)
    return null
  }
}

export async function initSentry(app, options = {}) {
  const { dsn, environment, tenantKey } = options
  if (!dsn) {
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
    integrations: (defaultIntegrations) => [
      ...defaultIntegrations,
      Sentry.browserTracingIntegration(),
    ],
  })

  _initialized = true
  _setTag = Sentry.setTag

  if (tenantKey) {
    Sentry.setTag('tenant_key', tenantKey)
  }

  return true
}

export function setSentryTenantKey(tenantKey) {
  if (!_initialized || !_setTag) return
  if (!tenantKey) return
  _setTag('tenant_key', tenantKey)
}

function _resetSentryForTests() {
  _setTag = null
  _initialized = false
}
