
export async function handleAuthFailure(error) {
  const { default: router } = await import('@/router')

  try {
    const resolved = router.resolve(window.location.pathname + window.location.search)
    if (resolved?.meta?.requiresAuth === false) {
      return Promise.reject(error)
    }
  } catch {
    // Resolution failed -- fall through to legacy path-based handling.
  }

  try {
    const { default: setupService } = await import('@/services/setupService')
    const setupData = await setupService.checkEnhancedStatus()
    if (setupData.is_fresh_install) {
      router.push('/welcome')
      return Promise.reject(error)
    }
  } catch {
    // Secure fallback to login
  }

  const currentPath = window.location.pathname + window.location.search
  if (!currentPath.includes('/login') && !currentPath.includes('/welcome')) {
    router.push({ path: '/login', query: { redirect: currentPath } })
  }
  return Promise.reject(error)
}

export function normalizeRejection(value) {
  if (value instanceof Error) return value
  if (value && typeof value === 'object' && (value.response || value.config)) {
    return value
  }
  const normalized = new Error(
    typeof value === 'string' && value ? value : 'An unexpected error occurred',
  )
  normalized.errorCode = 'UNKNOWN_ERROR'
  normalized.cause = value
  normalized.isNormalizedRejection = true
  return normalized
}
