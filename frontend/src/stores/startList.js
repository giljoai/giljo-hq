import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import api from '@/services/api'

const START_LIST_ROW_COUNT = 6
const ROW_KEYS = ['tool_connected', 'skills_installed', 'product_exists', 'project_staged', 'project_built']
const NO_PROJECT_YET = Object.freeze({ done: false, project_id: null, project_name: null })

function validShape(data) {
  const rows = data?.rows
  return (
    rows &&
    ROW_KEYS.every((k) => rows[k] && typeof rows[k].done === 'boolean') &&
    Number.isInteger(data.done_count)
  )
}

export const useStartListStore = defineStore('startList', () => {
  const rows = ref(null)
  const doneCount = ref(0)
  const loaded = computed(() => rows.value !== null)
  const allDone = computed(() => loaded.value && doneCount.value >= START_LIST_ROW_COUNT)

  let inflight = null
  let again = false

  async function readOnce() {
    try {
      const { data } = await api.onboarding.startList()
      if (!validShape(data)) return
      rows.value = { project_created: NO_PROJECT_YET, ...data.rows }
      doneCount.value = data.done_count
    } catch {
      /* keep the last known state; the next trigger tries again */
    }
  }

  async function run() {
    do {
      again = false
      await readOnce()
    } while (again)
  }

  function refresh({ force = false } = {}) {
    if (inflight) {
      if (force) again = true
      return inflight
    }
    inflight = run().finally(() => {
      inflight = null
    })
    return inflight
  }

  return { rows, doneCount, stepCount: START_LIST_ROW_COUNT, loaded, allDone, refresh }
})
