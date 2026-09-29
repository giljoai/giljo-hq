
import { ref } from 'vue'

export function useFoldSet(storageKey) {
  const folded = ref(new Set(readStored()))

  function readStored() {
    try {
      const raw = window.localStorage.getItem(storageKey)
      const parsed = raw ? JSON.parse(raw) : []
      return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : []
    } catch {
      return []
    }
  }

  function persist() {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify([...folded.value]))
    } catch {
      // Storage refused: the fold still applies for this page view.
    }
  }

  function isFolded(id) {
    return folded.value.has(id)
  }

  function toggle(id) {
    const next = new Set(folded.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    folded.value = next
    persist()
  }

  function unfold(id) {
    if (!folded.value.has(id)) return
    const next = new Set(folded.value)
    next.delete(id)
    folded.value = next
    persist()
  }

  return { folded, isFolded, toggle, unfold }
}
