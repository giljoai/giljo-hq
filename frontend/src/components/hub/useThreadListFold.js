import { ref } from 'vue'

export const OPEN_THREAD_CAP = 5
const SHOW_ALL_KEY = 'giljo.hub.threadList.showAll'
const RESOLVED_OPEN_KEY = 'giljo.hub.threadList.resolvedOpen'

function readFlag(key) {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function writeFlag(key, value) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    // Storage unavailable: the choice holds for this page load only.
  }
}

export function useThreadListFold() {
  const showAll = ref(readFlag(SHOW_ALL_KEY))
  const resolvedOpen = ref(readFlag(RESOLVED_OPEN_KEY))

  function setShowAll(value) {
    showAll.value = !!value
    writeFlag(SHOW_ALL_KEY, showAll.value)
  }

  function setResolvedOpen(value) {
    resolvedOpen.value = !!value
    writeFlag(RESOLVED_OPEN_KEY, resolvedOpen.value)
  }

  return { showAll, resolvedOpen, setShowAll, setResolvedOpen }
}
