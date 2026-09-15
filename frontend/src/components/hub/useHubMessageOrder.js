import { ref, computed } from 'vue'

export const OLDEST_FIRST = 'oldest'
export const NEWEST_FIRST = 'newest'
export const MESSAGE_ORDER_KEY = 'giljo.hub.messageOrder'

const VALID = new Set([OLDEST_FIRST, NEWEST_FIRST])

function readStored() {
  try {
    const raw = localStorage.getItem(MESSAGE_ORDER_KEY)
    return VALID.has(raw) ? raw : OLDEST_FIRST
  } catch {
    return OLDEST_FIRST
  }
}

let order = null

function state() {
  if (!order) order = ref(readStored())
  return order
}

export function useHubMessageOrder() {
  const current = state()

  function setOrder(next) {
    if (!VALID.has(next)) return
    current.value = next
    try {
      localStorage.setItem(MESSAGE_ORDER_KEY, next)
    } catch {
      // Storage unavailable (private mode, quota): the choice still holds for this
      // session; it simply will not survive a reload.
    }
  }

  return {
    order: current,
    newestFirst: computed(() => current.value === NEWEST_FIRST),
    setOrder,
  }
}

export function _resetHubMessageOrderForTests() {
  order = null
}
