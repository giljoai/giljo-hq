export function createReconnectPolicy({ onReconnectNeeded, slowRetryDelay = 60000, log = () => {} }) {
  let slowRetryTimer = null
  let armed = false

  const hasWindow = typeof window !== 'undefined'
  const hasDocument = typeof document !== 'undefined'

  function handleOnline() {
    log('Network online — attempting immediate reconnect')
    onReconnectNeeded('online')
  }

  function handleVisibility() {
    if (hasDocument && document.visibilityState === 'visible') {
      log('Tab visible — attempting immediate reconnect')
      onReconnectNeeded('visibility')
    }
  }

  function arm() {
    if (armed) {
      return
    }
    armed = true
    slowRetryTimer = setInterval(() => onReconnectNeeded('slow-retry'), slowRetryDelay)
    if (hasWindow) {
      window.addEventListener('online', handleOnline)
    }
    if (hasDocument) {
      document.addEventListener('visibilitychange', handleVisibility)
    }
    log(`Reconnect policy armed (slow retry every ${slowRetryDelay}ms + online/visibility re-arm)`)
  }

  function disarm() {
    if (!armed) {
      return
    }
    armed = false
    if (slowRetryTimer) {
      clearInterval(slowRetryTimer)
      slowRetryTimer = null
    }
    if (hasWindow) {
      window.removeEventListener('online', handleOnline)
    }
    if (hasDocument) {
      document.removeEventListener('visibilitychange', handleVisibility)
    }
    log('Reconnect policy disarmed')
  }

  return {
    arm,
    disarm,
    isArmed: () => armed,
  }
}
