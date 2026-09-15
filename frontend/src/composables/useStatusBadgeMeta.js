import { computed } from 'vue'

const FALLBACK_HEX = '#9e9e9e'

function formatFallbackLabel(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : 'Unknown'
}

function resolveColorToken(token) {
  if (!token) return FALLBACK_HEX
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return FALLBACK_HEX
  }
  try {
    const value = getComputedStyle(document.documentElement)
      .getPropertyValue(`--${token}`)
      .trim()
    if (!value) return FALLBACK_HEX
    return value
  } catch {
    return FALLBACK_HEX
  }
}

export function useStatusBadgeMeta(statusRef, store) {
  const meta = computed(() => store.getMeta(statusRef.value))

  const statusLabel = computed(() =>
    meta.value ? meta.value.label : formatFallbackLabel(statusRef.value),
  )

  const colorHex = computed(() =>
    meta.value ? resolveColorToken(meta.value.color_token) : FALLBACK_HEX,
  )

  return { meta, statusLabel, colorHex }
}
