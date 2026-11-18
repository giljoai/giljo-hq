const RETRYABLE = new Set([429, 503])
const BACKOFF_MS = [1000, 2000, 4000]

const MAX_RETRIES = 3
const MAX_JITTER_MS = 250

const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const defaultJitter = () => Math.floor(Math.random() * MAX_JITTER_MS)

function retryDelayMs(error, attempt) {
  const header = error?.response?.headers?.['retry-after']
  const seconds = Number(header)
  if (header !== undefined && header !== '' && Number.isFinite(seconds) && seconds >= 0) {
    return seconds * 1000
  }
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
}

export async function retryOnThrottle(
  fn,
  { maxWaitMs = 10000, sleep = defaultSleep, jitter = defaultJitter } = {},
) {
  let waited = 0
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn()
    } catch (error) {
      if (!RETRYABLE.has(error?.response?.status)) throw error
      if (attempt >= MAX_RETRIES) throw error
      const delay = retryDelayMs(error, attempt) + jitter()
      if (waited + delay > maxWaitMs) throw error
      waited += delay
      await sleep(delay)
    }
  }
}
