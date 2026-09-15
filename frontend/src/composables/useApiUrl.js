

export function getApiBaseUrl() {
  const envUrl = import.meta.env.VITE_API_URL
  if (envUrl && (envUrl.startsWith('http://') || envUrl.startsWith('https://'))) {
    return envUrl.replace(/\/$/, '')
  }
  if (typeof window !== 'undefined' && window.API_BASE_URL) {
    return window.API_BASE_URL.replace(/\/$/, '')
  }
  if (import.meta.env.DEV) {
    return ''
  }
  if (typeof window !== 'undefined' && window.location) {
    return window.location.origin
  }
  return ''
}

export function getWsBaseUrl() {
  const base = getApiBaseUrl()
  if (!base) return ''
  return base.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')
}
