/**
 * FE-9407: reconcile the roadmap "Waiting for your agent" spinner against the
 * roadmap's own last-saved time.
 *
 * The spinner's RAISE is durable — a roadmap:agent_active event stamps
 * localStorage and the stamp re-raises the spinner on every remount inside the
 * safety window. Its CLEAR was ephemeral: a one-shot roadmap:updated WS event
 * consumed only while RoadmapView is mounted with a live socket. A save landing
 * while the view was unmounted, or behind a dead socket, therefore broadcast
 * into a void and left the spinner re-raising over freshly rendered rows.
 *
 * `roadmap.last_generated_at` is the durable record of that save (stamped
 * server-side on every write, returned by the GET the view already performs on
 * mount). These helpers are the missing comparison, kept out of the view so the
 * decision is testable on its own and the view keeps only its two call sites.
 *
 * Edition scope: CE.
 */

/**
 * How far a save must postdate the stamp before it counts as answering it.
 *
 * The stamp is a client `Date.now()`; the save is server UTC. The two clocks
 * are not the same clock, so a difference smaller than this is skew, not a
 * save. The margin is tiny against the spinner's ~150s safety window and
 * against any realistic agent-connect-to-save gap.
 */
const SAVE_SUPERSEDES_SKEW_MS = 5000

/**
 * True when the roadmap was saved after the waiting stamp was written.
 *
 * Every condition here fails toward LEAVING THE SPINNER UP, deliberately.
 * Clearing a spinner the user still needs breaks the mid-build reload
 * continuity TSK-6243 built on purpose; failing to clear one only falls back to
 * the prior behavior, which the safety timeout already bounds. So a save must
 * beat the stamp by a clear margin, and the roadmap must actually have rows —
 * the defect is a spinner standing over a delivered roadmap, so an empty one is
 * still genuinely waiting.
 *
 * @param {object|null} roadmap - the roadmap object from GET /roadmap
 * @param {Array} items - the roadmap's items, as rendered
 * @param {number} stampedAt - epoch ms from the persisted agent-active stamp
 * @returns {boolean}
 */
export function agentSavedAfter(roadmap, items, stampedAt) {
  if (!Number.isFinite(stampedAt)) return false
  if (!Array.isArray(items) || items.length === 0) return false
  const raw = roadmap?.last_generated_at
  if (!raw) return false
  // Date.parse reads a timezone-less date-time as LOCAL. The server sends UTC,
  // so normalize first rather than inherit the viewer's offset — untreated,
  // a negative-offset viewer would read the save as hours later than it was,
  // which is the over-clearing direction.
  const iso = /([zZ]|[+-]\d{2}:?\d{2})$/.test(raw) ? raw : `${raw}Z`
  // NaN comparisons are false, so an unparseable timestamp declines here.
  return Date.parse(iso) > stampedAt + SAVE_SUPERSEDES_SKEW_MS
}

/**
 * Same decision, reading the stamp from localStorage itself.
 *
 * For callers that do not already hold the stamp — notably the WS reconnect
 * resync, where the spinner is typically ALREADY up, so the view's mount-time
 * rehydrate would return at its own `waiting` guard in exactly the case this
 * exists to catch.
 *
 * @param {object|null} roadmap
 * @param {Array} items
 * @param {string|null} storageKey - the per-product agent-active stamp key
 * @returns {boolean}
 */
export function waitIsSuperseded(roadmap, items, storageKey) {
  if (!storageKey) return false
  let raw = null
  try {
    raw = localStorage.getItem(storageKey)
  } catch {
    return false // localStorage unavailable (private mode / quota) — non-fatal
  }
  if (raw === null) return false
  return agentSavedAfter(roadmap, items, Number(raw))
}
