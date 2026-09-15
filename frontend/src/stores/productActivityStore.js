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

  function recordActivity(productId) {
    if (!productId) return
    const next = new Map(countsByProduct.value)
    next.set(productId, (next.get(productId) ?? 0) + 1)
    countsByProduct.value = next
  }

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
