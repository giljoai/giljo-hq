/**
 * popoutRegistry.js — FE-9553, simplified by FE-9586
 *
 * The live browser popouts, addressable by tag, so that the state which raised
 * one can also close it.
 *
 * Ruling 4(c): popouts follow banner state INCLUDING DEATH. The Notification
 * handle is created deep inside the signal path and the thing that knows the
 * banner has cleared is somewhere else entirely, so the handle has to be
 * findable between the two. This module is that lookup and nothing more -- it
 * holds no policy about WHEN to close, only the ability to.
 *
 * Module scope rather than a Pinia store on purpose: an OS notification handle
 * is not application state. It cannot be serialised, restored, or meaningfully
 * inspected by a devtools timeline, and it outlives no page load. A store would
 * imply all three.
 *
 * ONE KIND OF POPOUT (FE-9586). This module used to hold two, and the split was
 * load-bearing at the time: a baton and an approval had reactive state saying
 * whether their banner was still up, while a mention had none, so reconciling a
 * mention would have closed it instantly. Mentions and directed action-requests
 * are now state-backed too (useThreadPostAttention, off a server projection), so
 * the distinction has no members left and the ten-minute TTL that stood in for
 * missing state is gone with it. A deadline was always the wrong shape for a
 * signal somebody still owes an answer to; it existed because there was nothing
 * better to observe.
 *
 * Edition Scope: Both
 */

/** tag -> Notification handle */
const open = new Map()

/**
 * Record a freshly opened popout so its state can close it later.
 *
 * Re-registering the same tag replaces the previous entry, mirroring what the
 * OS itself does with a repeated tag: one signal, one notification.
 *
 * @param {string} tag - from popoutTag(); the shared derivation
 * @param {{close: Function}} popout - the Notification handle
 */
export function registerPopout(tag, popout) {
  if (!tag || !popout) return
  open.set(tag, popout)
}

/**
 * Close one popout and forget it. Safe to call for a tag we do not hold.
 *
 * Module-private since FE-9586. It was exported for the TTL timer that used to
 * close unreconciled popouts on a deadline; with every reason state-backed there is
 * no deadline and no outside caller, and leaving the export would have it read as
 * part of this module's contract when nothing depends on it.
 *
 * An OS-backed handle can throw or already be dead, and a caller mid-reconcile
 * must not be derailed by one bad handle, so the failure is contained here
 * rather than at every call site. The entry is dropped either way: keeping a
 * handle we have already failed to close would only guarantee we retry it
 * forever.
 */
function closePopout(tag) {
  const popout = open.get(tag)
  if (!popout) return

  open.delete(tag)

  try {
    popout.close()
  } catch {
    // Handle already dead or unavailable — nothing to undo.
  }
}

/**
 * Close every popout whose banner state has gone.
 *
 * CALLERS MUST NOT CALL THIS WITH A LIST THEY HAVE NOT LOADED. Every tag absent
 * from `liveTags` is closed, so an empty set from an unhydrated source closes
 * everything — the one failure this whole mechanism has to avoid. The
 * loaded-vs-empty distinction lives with the caller that owns the state; see
 * useBannerPopoutLifecycle.
 *
 * @param {Set<string>|Array<string>} liveTags - tags whose banners are still up
 */
export function reconcilePopouts(liveTags) {
  const live = liveTags instanceof Set ? liveTags : new Set(liveTags || [])

  // Snapshot the keys: closePopout mutates the Map, and iterating it directly
  // while deleting is how you skip entries.
  for (const tag of [...open.keys()]) {
    if (live.has(tag)) continue
    closePopout(tag)
  }
}

/** The tags currently held. Test and diagnostic use. */
export function registeredPopoutTags() {
  return [...open.keys()]
}

/**
 * Drop every entry without closing anything.
 *
 * For test isolation only: this module is module-scoped, so without it one
 * spec's popouts would be visible to the next in the same worker.
 */
export function clearPopoutRegistry() {
  open.clear()
}
