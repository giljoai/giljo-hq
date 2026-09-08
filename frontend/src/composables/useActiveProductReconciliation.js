/**
 * useActiveProductReconciliation.js — FE-9412, demoted by FE-9502c
 *
 * The staleness backstop for the DISPLAYED server-active product.
 *
 * `product:status:changed` reaches every session whose socket is alive. A
 * session whose socket died, slept with the tab, or dropped the frame never
 * gets it, and nothing replays it — which is how one browser displayed a stale
 * active product for over an hour while the server was never wrong.
 *
 * So the live event is never trusted alone. Whenever the session comes back
 * into play — the tab becomes visible, the window takes focus, or the socket
 * reconnects — it re-validates against persisted server state with one
 * lightweight GET. Same reconciliation rule as FE-9407/FE-9166.
 *
 * FE-9502c: it no longer re-scopes the session. Under the tabbed shell,
 * `currentProductId` is the VIEWED TAB (UI-local), not the server's active
 * product — a background focus/reconnect event silently switching it would
 * be auto-navigation. Only `productStore.activeProduct` (now a
 * display value / legacy-default) is kept fresh.
 *
 * Returns `stop` because callers mount this from onMounted, where the
 * component's effect scope is no longer current and onScopeDispose cannot fire.
 */
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

  // A reconnect is the other way a session learns it may have missed something.
  const unregisterResync = registerReconnectResync(reconcile)

  if (typeof window !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
    window.addEventListener('focus', reconcile)
  }

  let stopped = false

  /** Detach every listener and the resync registration. Idempotent. */
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
