
const SAVE_SUPERSEDES_SKEW_MS = 5000

export function agentSavedAfter(roadmap, items, stampedAt) {
  if (!Number.isFinite(stampedAt)) return false
  if (!Array.isArray(items) || items.length === 0) return false
  const raw = roadmap?.last_generated_at
  if (!raw) return false
  const iso = /([zZ]|[+-]\d{2}:?\d{2})$/.test(raw) ? raw : `${raw}Z`
  return Date.parse(iso) > stampedAt + SAVE_SUPERSEDES_SKEW_MS
}

export function waitIsSuperseded(roadmap, items, storageKey) {
  if (!storageKey) return false
  let raw = null
  try {
    raw = localStorage.getItem(storageKey)
  } catch {
    return false
  }
  if (raw === null) return false
  return agentSavedAfter(roadmap, items, Number(raw))
}
