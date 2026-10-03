import { watch } from 'vue'
import api from '@/services/api'
import { toolIdForHarness } from '@/config/setupTools'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useConnectedToolsResumeSeed({ currentStep, selectedTools, step2Data }) {
  const { showToast } = useToast()
  let seeded = false

  async function seed() {
    if (seeded) return
    if (currentStep() < 2) return
    if (step2Data.value?.connectedTools?.length) return
    try {
      const { data } = await api.connect.credentialStatus()
      seeded = true
      const connectedHarnesses = data?.connected_harnesses || {}
      const ids = new Set()
      for (const harness of Object.keys(connectedHarnesses)) {
        const id = toolIdForHarness(harness)
        if (id && selectedTools().includes(id)) ids.add(id)
      }
      if (ids.size > 0) {
        step2Data.value = { ...step2Data.value, connectedTools: [...ids] }
      }
    } catch (e) {
      showToast({
        message: `Could not read which tools are connected: ${parseErrorResponse(e).message}`,
        type: 'error',
      })
    }
  }

  watch(currentStep, seed, { immediate: true })
}
