import { onScopeDispose, getCurrentScope } from 'vue'
import { useProductStore } from '@/stores/products'
import { registerReconnectResync } from '@/stores/websocketEventRouter'

export function useActiveProductReconciliation() {
  const productStore = useProductStore()

  async function reconcile() {
    try {
      await productStore.revalidateActiveProduct()
    } catch (error) {
      console.warn('[PRODUCTS] Active-product reconciliation failed:', error)
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      reconcile()
    }
  }

  const unregisterResync = registerReconnectResync(reconcile)

  if (typeof window !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
    window.addEventListener('focus', reconcile)
  }

  let stopped = false

  function stop() {
    if (stopped) {
      return
    }
    stopped = true

    if (typeof window !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange)
      window.removeEventListener('focus', reconcile)
    }
    unregisterResync?.()
  }

  if (getCurrentScope()) {
    onScopeDispose(stop)
  }

  return { stop }
}
