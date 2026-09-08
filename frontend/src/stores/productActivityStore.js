/**
 * productActivityStore.js — FE-9502d
 *
 * The activity surface for a PRODUCT you do not currently have viewed as a
 * tab. One level up from globalActivityStore.js (FE-9501b, D5 — the same
 * pattern for a PROJECT you don't have open): dumb COUNT, never hydrate,
 * keyed by product_id instead of project_id. The consuming UI
 * (ProductTabStrip's per-tab badge) decides what to show; switching to a
 * tab clears its count, mirroring clearActivity-on-open.
 *
 * Fed by a separate, additive routing pass (routeProductActivityEvent in
 * websocketEventRouter.js) that is NOT subject to the viewed-tab filter --
 * only the tenant check. `conductor_job_minter.py`'s project-less
 * `agent:created` carries no product_id (sequence_runs has no such column)
 * and is a legitimate no-badge case, not a bug -- recordActivity is a no-op
 * on a falsy id, same as globalActivityStore.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const useProductActivityStore = defineStore('productActivity', () => {
  const countsByProduct = ref(new Map())

  const totalCount = computed(() => {
    let sum = 0
    for (const n of countsByProduct.value.values()) sum += n
    return sum
  })

  const activeProductIds = computed(() => Array.from(countsByProduct.value.keys()))

  function getCount(productId) {
    if (!productId) return 0
    return countsByProduct.value.get(productId) ?? 0
  }

  /** Record one unit of activity for a product. Cheap: a Map write, never a fetch. */
  function recordActivity(productId) {
    if (!productId) return
    const next = new Map(countsByProduct.value)
    next.set(productId, (next.get(productId) ?? 0) + 1)
    countsByProduct.value = next
  }

  /** Clear the count for a product -- called when the user switches to its tab. */
  function clearActivity(productId) {
    if (!productId || !countsByProduct.value.has(productId)) return
    const next = new Map(countsByProduct.value)
    next.delete(productId)
    countsByProduct.value = next
  }

  function $reset() {
    countsByProduct.value = new Map()
  }

  return {
    countsByProduct,
    totalCount,
    activeProductIds,
    getCount,
    recordActivity,
    clearActivity,
    $reset,
  }
})
