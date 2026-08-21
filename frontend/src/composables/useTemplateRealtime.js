/**
 * useTemplateRealtime.js — FE-9385c
 *
 * Keeps the in-memory template rows in step with the outside world, so the
 * Agents table reflects an export or a change made somewhere else without a
 * manual refresh. Extracted verbatim from TemplateManager.vue.
 *
 * Three inbound signals, all handled here:
 *   - `template:exported`         — stamps last_exported_at, clears staleness
 *   - `template:updated`          — mirrors is_active / may_be_stale changes
 *   - `setup:agents_downloaded`   — an MCP giljo_setup "Agents only" download
 *
 * They arrive two ways, which is why both paths exist: the event router
 * dispatches window CustomEvents, while the parent view (ToolsView) provides a
 * `templateExportEvent` ref that this watches. Both funnel into the same
 * handler, and both drop anything belonging to another tenant.
 *
 * Window listeners are registered on mount and removed on unmount by this
 * composable itself — the caller wires nothing.
 *
 * @param {import('vue').Ref<Array>} templates - the reactive template rows to patch in place
 * @param {Function} reloadActiveCount - refetch the active-agent count
 *
 * Edition scope: CE
 */
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { useUserStore } from '@/stores/user'

export function useTemplateRealtime(templates, reloadActiveCount) {
  // Handover 0335: WebSocket setup for real-time export status updates
  const userStore = useUserStore()
  const currentTenantKey = computed(() => userStore.currentUser?.tenant_key)

  // Handover 0335: Inject template export event from parent (UserSettings.vue)
  const templateExportEvent = inject('templateExportEvent', ref(null))

  // Handover 0335: Handle template export WebSocket event
  const handleTemplateExported = (data) => {
    const { tenant_key: tenantKey, template_ids: templateIds, exported_at: exportedAt } = data
    if (!tenantKey || !templateIds || !exportedAt) return
    if (tenantKey !== currentTenantKey.value) return

    const templateIdSet = new Set(templateIds)
    templates.value.forEach((template) => {
      if (templateIdSet.has(template.id)) {
        template.last_exported_at = exportedAt
        template.may_be_stale = false
      }
    })
  }

  // Handle real-time template updates via WebSocket (enable/disable, field changes)
  const handleTemplateUpdated = (data) => {
    if (!data?.template_id) return
    const template = templates.value.find((t) => t.id === data.template_id)
    if (template) {
      if (data.is_active !== undefined) template.is_active = data.is_active
      if (data.may_be_stale !== undefined) template.may_be_stale = data.may_be_stale
      // Refresh active count when is_active changes
      if (data.updated_fields?.includes('is_active')) reloadActiveCount()
    }
  }

  // Handle agent template downloads via MCP (giljo_setup, "Agents only") — clear staleness flags
  const handleAgentsDownloaded = () => {
    const now = new Date().toISOString()
    templates.value.forEach((template) => {
      template.last_exported_at = now
      template.may_be_stale = false
      template.user_managed_export = false
    })
  }

  // Window event wrappers (event router dispatches as CustomEvent, not WS store)
  const onAgentsDownloaded = (e) => handleAgentsDownloaded(e.detail)
  const onTemplateExported = (e) => handleTemplateExported(e.detail)
  const onTemplateUpdated = (e) => handleTemplateUpdated(e.detail)

  onMounted(() => {
    window.addEventListener('template:exported', onTemplateExported)
    window.addEventListener('setup:agents_downloaded', onAgentsDownloaded)
    window.addEventListener('template:updated', onTemplateUpdated)
  })

  onUnmounted(() => {
    window.removeEventListener('template:exported', onTemplateExported)
    window.removeEventListener('setup:agents_downloaded', onAgentsDownloaded)
    window.removeEventListener('template:updated', onTemplateUpdated)
  })

  // Handover 0335: Watch for export events from parent (UserSettings.vue)
  watch(
    templateExportEvent,
    (newEvent) => {
      if (!newEvent) return
      if (newEvent.tenant_key !== currentTenantKey.value) return
      handleTemplateExported(newEvent)
    },
    { deep: true }
  )

  return { handleTemplateExported, handleTemplateUpdated, handleAgentsDownloaded }
}
