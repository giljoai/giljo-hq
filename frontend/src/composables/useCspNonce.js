
const META_NAME = 'csp-nonce'

export function readCspNonce() {
  try {
    const meta = document.querySelector(`meta[name="${META_NAME}"]`)
    if (!meta) return ''
    return meta.getAttribute('content') || ''
  } catch {
    return ''
  }
}

export function applyNonceToApp(app) {
  const nonce = readCspNonce()

  try {
    if (typeof window !== 'undefined') {
      window.__CSP_NONCE__ = nonce
    }
  } catch {
    /* ignore — non-browser env */
  }

  if (!app || !app.config) return
  if (!app.config.globalProperties) return
  app.config.globalProperties.$nonce = nonce
}
