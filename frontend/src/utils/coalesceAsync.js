export function coalesceAsync(fn) {
  let inflight = null
  let again = false

  return function run() {
    if (inflight) {
      again = true
      return inflight
    }
    inflight = (async () => {
      try {
        do {
          again = false
          await fn()
        } while (again)
      } finally {
        inflight = null
      }
    })()
    return inflight
  }
}
