import { watch } from 'vue'
import api from '@/services/api'
import { useIntegrationStatus } from '@/composables/useIntegrationStatus'

export function useDeferredHomeData({ onboardingComplete, showIntegReminder, templates, totalSlots, productId }) {
  const { gitEnabled, serenaEnabled, refresh: refreshIntegrationStatus } = useIntegrationStatus({
    immediate: false,
  })

  let teamTemplatesLoaded = false
  async function loadTeamTemplates() {
    if (teamTemplatesLoaded) return
    const scope = productId?.value || null
    if (!scope) {
      templates.value = []
      return
    }
    teamTemplatesLoaded = true
    const [listed, counted, assigned] = await Promise.allSettled([
      Promise.resolve().then(() => api.templates.list(scope)),
      Promise.resolve().then(() => api.templates.activeCount(scope)),
      Promise.resolve().then(() => api.assignments.list(scope)),
    ])

    if (counted.status === 'fulfilled' && counted.value?.data?.max_slots) {
      totalSlots.value = counted.value.data.max_slots
    }
    if (listed.status !== 'fulfilled') return

    const enabled = new Map(
      (assigned.status === 'fulfilled' ? assigned.value?.data?.assignments || [] : []).map((a) => [
        a.template_id,
        a.is_active,
      ]),
    )
    templates.value = (listed.value?.data || []).map((t) => ({
      ...t,
      product_active: enabled.get(t.id) ?? false,
    }))
  }

  let integrationStatusLoaded = false
  function loadIntegrationStatusOnce() {
    if (integrationStatusLoaded) return
    integrationStatusLoaded = true
    refreshIntegrationStatus()
  }

  watch(onboardingComplete, (ready) => { if (ready) loadTeamTemplates() }, { immediate: true })
  watch(() => productId?.value, (id) => { if (id && onboardingComplete.value) loadTeamTemplates() })
  watch(showIntegReminder, (show) => { if (show) loadIntegrationStatusOnce() }, { immediate: true })

  return { gitEnabled, serenaEnabled }
}
