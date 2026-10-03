
const SENTINEL_PREFIX = 'giljo:chunk-reload:'

const RELOAD_WINDOW_MS = 10000

const STALE_MESSAGE = 'A new version is available — please refresh the page.'

const CHUNK_ERROR_PATTERNS = [
  /failed to fetch dynamically imported module/i,
  /error loading dynamically imported module/i,
  /importing a module script failed/i,
  /dynamically imported module/i,
  /unable to preload css/i,
  /failed to load module script/i,
  /expected a javascript[ -]?module/i,
  /mime type \(['"]text\/html['"]\)/i,
]

export function isChunkLoadError(error) {
  if (!error) return false
  const message =
    typeof error === 'string'
      ? error
      : error.message || (error.reason && error.reason.message) || String(error)
  if (!message) return false
  return CHUNK_ERROR_PATTERNS.some((re) => re.test(message))
}

function notifyStale(toast) {
  if (typeof toast === 'function') {
    toast(STALE_MESSAGE)
    return
  }
  if (typeof window === 'undefined') return
  if (window.$toast && typeof window.$toast.warning === 'function') {
    window.$toast.warning(STALE_MESSAGE)
    return
  }
  if (typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(
      new CustomEvent('show-toast', {
        detail: { message: STALE_MESSAGE, type: 'warning' },
      })
    )
  }
}

export function maybeReloadForChunkError(key, deps = {}) {
  const hasWindow = typeof window !== 'undefined'
  const pathKey = key || (hasWindow ? window.location.pathname : '/')
  const storage = deps.storage || (hasWindow ? window.sessionStorage : null)
  const reload = deps.reload || (() => window.location.reload())
  const nowFn = deps.now || (() => Date.now())
  const sentinelKey = SENTINEL_PREFIX + pathKey

  let last = 0
  try {
    last = storage ? Number(storage.getItem(sentinelKey)) || 0 : 0
  } catch {
    last = 0
  }

  const ts = nowFn()
  if (last && ts - last < RELOAD_WINDOW_MS) {
    notifyStale(deps.toast)
    return false
  }

  try {
    if (storage) storage.setItem(sentinelKey, String(ts))
  } catch {
    // sessionStorage unavailable (private mode / disabled): without persistence
    // we cannot loop-guard, but a single reload is still the right first move
    // and the browser will not tight-loop on one navigation.
  }

  reload()
  return true
}

export const __testing = { SENTINEL_PREFIX, RELOAD_WINDOW_MS, STALE_MESSAGE }
