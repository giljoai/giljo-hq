
let _setTag = null
let _setAttribute = null
let _initialized = false

const PII_DENY = ['forwarded', '-ip', 'remote-', 'via', '-user']
const SENTRY_DATA_COLLECTION = Object.freeze({
  userInfo: false,
  cookies: false,
  httpHeaders: { request: { deny: PII_DENY }, response: { deny: PII_DENY } },
  httpBodies: [],
  urlQueryParams: { deny: PII_DENY },
  genAI: { inputs: false, outputs: false },
  databaseQueryData: false,
  queues: false,
  graphQL: { document: false, variables: false },
})

async function loadSentry() {
  try {
    const { init, browserTracingIntegration, setTag, setAttribute } = await import('@sentry/vue')
    return { init, browserTracingIntegration, setTag, setAttribute }
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
    dataCollection: SENTRY_DATA_COLLECTION,
    integrations: (defaultIntegrations) => [
      ...defaultIntegrations,
      Sentry.browserTracingIntegration(),
    ],
  })

  _initialized = true
  _setTag = Sentry.setTag
  _setAttribute = Sentry.setAttribute || null

  if (tenantKey) {
    _applyTenantKey(tenantKey)
  }

  return true
}

export function setSentryTenantKey(tenantKey) {
  if (!_initialized || !_setTag) return
  if (!tenantKey) return
  _applyTenantKey(tenantKey)
}

function _applyTenantKey(tenantKey) {
  _setTag('tenant_key', tenantKey)
  if (_setAttribute) _setAttribute('tenant_key', tenantKey)
}

function _resetSentryForTests() {
  _setTag = null
  _setAttribute = null
  _initialized = false
}
