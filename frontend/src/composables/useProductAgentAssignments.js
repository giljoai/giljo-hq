import { computed } from 'vue'
import api from '@/services/api'
import { useProductStore } from '@/stores/products'

/**
 * BE-9385a — per-product agent enablement for the Agents screen.
 *
 * The inline Active switch used to write the tenant-wide `agent_templates.is_active`
 * flag, so curating agents while one product was active changed them for every
 * product. It now writes the `product_agent_assignments` junction, scoped to the
 * ACTIVE product, and the row shows `product_active` overlaid on top of the tenant
 * flag.
 *
 * Keyed on the store's `activeProduct`, deliberately NOT `effectiveProductId`.
 * `effectiveProductId` prefers `currentProductId` — the product the user is
 * browsing — while the server exports and spawns for the product that is actually
 * ACTIVE (`Product.is_active`). Writing the junction for a browsed-but-inactive
 * product would put the screen and the export back out of step, which is the exact
 * class of defect this project removes.
 *
 * Tolerance mirrors the server: a template with no junction row shows the tenant
 * flag rather than an "off" the server would not agree with, and with no active
 * product at all the toggle falls back to the tenant-wide write.
 */
export function useProductAgentAssignments(templates, loadActiveCount) {
  const productStore = useProductStore()
  const activeProductId = computed(() => productStore.activeProduct?.id || null)

  const loadProductAssignments = async () => {
    const productId = activeProductId.value
    if (!productId) {
      templates.value.forEach((t) => delete t.product_active)
      return
    }
    try {
      const response = await api.assignments.list(productId)
      const byTemplateId = new Map(
        (response.data?.assignments || []).map((a) => [a.template_id, a.is_active]),
      )
      templates.value.forEach((t) => {
        if (byTemplateId.has(t.id)) t.product_active = byTemplateId.get(t.id)
        else delete t.product_active
      })
    } catch (error) {
      // Non-fatal: rows fall back to the tenant flag, which is what the server
      // selects anyway for a product with no junction rows.
      console.error('Failed to load per-product agent assignments:', error)
    }
  }

  /**
   * Enable/disable an agent. Returns true when the write was PER-PRODUCT; false
   * when there was no active product to scope to and the tenant-wide flag was
   * written instead (pre-BE-9385a behaviour, better than silently doing nothing).
   */
  const toggleAgent = async (template, newValue) => {
    const productId = activeProductId.value
    if (productId) {
      await api.assignments.toggle(productId, template.id, newValue)
      template.product_active = newValue
      return true
    }
    await api.templates.update(template.id, { is_active: newValue })
    template.is_active = newValue
    await loadActiveCount?.()
    return false
  }

  return { activeProductId, loadProductAssignments, toggleAgent }
}
