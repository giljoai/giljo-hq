
import { computed, ref } from 'vue'

export const BOARD_DENSITY_STORAGE_ITEM = 'jobs.density.v2'
export const BOARD_DENSITIES = Object.freeze({ DETAILED: 'detailed', COMPACT: 'compact' })
const KNOWN = new Set(Object.values(BOARD_DENSITIES))

function readStored() {
  try {
    const value = window.localStorage.getItem(BOARD_DENSITY_STORAGE_ITEM)
    return KNOWN.has(value) ? value : BOARD_DENSITIES.COMPACT
  } catch {
    return BOARD_DENSITIES.COMPACT
  }
}

export function useBoardDensity() {
  const density = ref(readStored())
  const isCompact = computed(() => density.value === BOARD_DENSITIES.COMPACT)

  function setDensity(value) {
    if (!KNOWN.has(value)) return
    density.value = value
    try {
      window.localStorage.setItem(BOARD_DENSITY_STORAGE_ITEM, value)
    } catch {
      // Storage refused (private window, blocked site data): the choice still
      // applies for this page view.
    }
  }

  return { density, isCompact, setDensity }
}
