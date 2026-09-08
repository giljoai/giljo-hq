import { computed } from 'vue'
import api from '@/services/api'
import { useProductStore } from '@/stores/products'

/**
 * BE-9385a — per-product agent enablement for the Agents screen.
 *
 * The inline Active switch used to write the tenant-wide `agent_templates.is_active`
 * flag, so curating agents while one product was viewed changed them for every
 * product. It now writes the `product_agent_assignments` junction, scoped to the
 * VIEWED product tab, and the row shows `product_active` overlaid on top of the
 * tenant flag.
 *
 * FE-9524/D1: keyed on `effectiveProductId` (the viewed tab), not the legacy
 * singular `productStore.activeProduct`. Before D1 retired "active product" as
 * a global concept, `is_active` was also what the server exported/spawned for,
 * so this deliberately keyed on it instead of the browsed tab. That is no
 * longer true (BE-9523 gives every export/spawn an explicit product_id) and
 * `activeProduct` no longer means "the one product in play" -- several may be
 * shown at once. Keying on it here would curate agents for whichever product
 * happens to be MOST RECENTLY shown, not the one on screen: the exact class of
 * stale-reader bug this project exists to remove (project record finding 3).
 *
 * Tolerance mirrors the server: a template with no junction row shows the tenant
 * flag rather than an "off" the server would not agree with, and with no product
 * tab viewed at all the toggle falls back to the tenant-wide write.
 */
export function useProductAgentAssignments(templates, loadActiveCount) {
  const productStore = useProductStore()
  const activeProductId = computed(() => productStore.effectiveProductId || null)

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
