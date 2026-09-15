
const open = new Map()

export function registerPopout(tag, popout) {
  if (!tag || !popout) return
  open.set(tag, popout)
}

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

export function reconcilePopouts(liveTags) {
  const live = liveTags instanceof Set ? liveTags : new Set(liveTags || [])

  for (const tag of [...open.keys()]) {
    if (live.has(tag)) continue
    closePopout(tag)
  }
}

export function registeredPopoutTags() {
  return [...open.keys()]
}

export function clearPopoutRegistry() {
  open.clear()
}
