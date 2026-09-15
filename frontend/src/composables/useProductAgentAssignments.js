import { computed, ref } from 'vue'
import api from '@/services/api'
import { useProductStore } from '@/stores/products'
import { templateRowActive } from '@/components/templates/templateTableConfig'

export function useProductAgentAssignments(templates, loadActiveCount) {
  const productStore = useProductStore()
  const activeProductId = computed(() => productStore.effectiveProductId || null)

  const loadedProductId = ref(null)
  const assignmentsLoading = ref(false)

  const loadProductAssignments = async () => {
    const productId = activeProductId.value
    if (!productId) {
      templates.value.forEach((t) => delete t.product_active)
      loadedProductId.value = null
      return
    }
    assignmentsLoading.value = true
    try {
      const response = await api.assignments.list(productId)
      if (activeProductId.value !== productId) return
      const rows = response.data?.assignments || []
      const byTemplateId = new Map(rows.map((a) => [a.template_id, a.is_active]))
      templates.value.forEach((t) => {
        t.product_active = byTemplateId.get(t.id) ?? false
      })
      loadedProductId.value = productId
    } catch (error) {
      console.error('Failed to load per-product agent assignments:', error)
      if (activeProductId.value !== productId) return
      templates.value.forEach((t) => delete t.product_active)
      loadedProductId.value = productId
    } finally {
      if (activeProductId.value === productId) assignmentsLoading.value = false
    }
  }

  const bulkRunning = ref(false)

  const toggleAgent = async (template, newValue, productId = loadedProductId.value) => {
    if (!productId) return false
    await api.assignments.toggle(productId, template.id, newValue)
    template.product_active = newValue
    await loadActiveCount?.()
    return true
  }

  const setAllForProduct = async (isActive, productId = loadedProductId.value) => {
    if (!productId) return { changed: 0, failed: [], overBudget: [] }
    bulkRunning.value = true
    try {
      let changed = 0
      const failed = []
      const overBudget = []
      for (const template of [...templates.value]) {
        if (template._system) continue
        if (templateRowActive(template) === isActive) continue
        try {
          await toggleAgent(template, isActive, productId)
          changed += 1
        } catch (error) {
          if (error?.response?.status === 409) {
            overBudget.push(template.name)
          } else {
            console.error('Failed to set agent for product:', error)
            failed.push(template.name)
          }
        }
      }
      return { changed, failed, overBudget }
    } finally {
      bulkRunning.value = false
    }
  }

  return {
    activeProductId,
    loadedProductId,
    assignmentsLoading,
    bulkRunning,
    loadProductAssignments,
    toggleAgent,
    setAllForProduct,
  }
}
