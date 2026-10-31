const RETRYABLE = new Set([429, 503])
const BACKOFF_MS = [1000, 2000, 4000]

const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function retryDelayMs(error, attempt) {
  const header = error?.response?.headers?.['retry-after']
  const seconds = Number(header)
  if (header !== undefined && header !== '' && Number.isFinite(seconds) && seconds >= 0) {
    return seconds * 1000
  }
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
}

export async function retryOnThrottle(fn, { maxWaitMs = 10000, sleep = defaultSleep } = {}) {
  let waited = 0
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn()
    } catch (error) {
      if (!RETRYABLE.has(error?.response?.status)) throw error
      const delay = retryDelayMs(error, attempt)
      if (waited + delay > maxWaitMs) throw error
      waited += delay
      await sleep(delay)
    }
  }
}
