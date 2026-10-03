import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export function createStatusesStore(storeId, fetchStatuses) {
  return defineStore(storeId, () => {
    const statuses = ref([])
    const loaded = ref(false)
    const loading = ref(false)

    let inFlight = null

    const validValues = computed(() => statuses.value.map((s) => s.value))

    const metaByValue = computed(() => {
      const map = new Map()
      for (const s of statuses.value) {
        map.set(s.value, s)
      }
      return map
    })

    function getMeta(value) {
      return metaByValue.value.get(value)
    }

    function isValid(value) {
      if (!value) return false
      return metaByValue.value.has(value)
    }

    async function ensureLoaded() {
      if (loaded.value) return
      if (inFlight) return inFlight

      loading.value = true
      inFlight = (async () => {
        try {
          const response = await fetchStatuses()
          if (!Array.isArray(response?.data)) {
            throw new Error(`Status list reply is not a list`)
          }
          statuses.value = response.data
          loaded.value = true
        } finally {
          loading.value = false
          inFlight = null
        }
      })()

      return inFlight
    }

    function reset() {
      statuses.value = []
      loaded.value = false
      loading.value = false
      inFlight = null
    }

    return {
      statuses,
      loaded,
      loading,
      validValues,
      ensureLoaded,
      getMeta,
      isValid,
      reset,
    }
  })
}
