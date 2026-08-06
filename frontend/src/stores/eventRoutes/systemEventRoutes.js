import { useAgentJobsStore } from '../agentJobsStore'
import { useNotificationStore } from '../notifications'
import { useProductStore } from '../products'
import { useTaskStore } from '../tasks'

function dispatchWindowEvent(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

/**
 * System, progress, product, and vision event route definitions.
 */
export const SYSTEM_EVENT_ROUTES = {
  // Handover 0386: Progress updates should NOT create messages
  // Handover 0402: Include todo_items array for Plan/TODOs tab
  // Handover 0462: Include agent_display_name and agent_name to prevent "??" avatar bug
  'job:progress_update': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()

      agentJobsStore.handleProgressUpdate?.({
        job_id: payload.job_id,
        agent_id: payload.agent_id,
        agent_display_name: payload.agent_display_name,
        agent_name: payload.agent_name,
        progress: payload.progress_percent,
        current_task: payload.current_task,
        todo_steps: payload.todo_steps,
        todo_items: payload.todo_items,
        last_progress_at: payload.last_progress_at,
        progress_data: payload.progress,
      })

      dispatchWindowEvent('job:progress_update', payload)
    },
  },

  // Products
  'product:memory:updated': { store: 'products', action: 'handleProductMemoryUpdated' },
  'product:status:changed': { store: 'products', action: 'handleProductStatusChanged' },

  'product:context_updated': {
    handler: async (data, { notificationStore }) => {
      notificationStore.addNotification({
        type: 'context_tuning',
        title: 'Product Context Updated',
        message: `${data.applied_count} section(s) updated via tuning review.`,
        metadata: { product_id: data.product_id },
      })
    },
  },

  // Vision Document Analysis — agent connected (Handover 0842c)
  'vision:analysis_started': {
    handler: async (payload) => {
      dispatchWindowEvent('vision-analysis-started', payload)
    },
  },

  // Vision Document Analysis — complete (Handover 0842c, extended BE-5118, FE-9121)
  // Refreshes the products list AND unconditionally write-throughs the full
  // product into productsById, so ProductForm's store-first gate/banner see
  // the flipped vision_analysis_complete flag even when this product isn't
  // the globally selected one (e.g. the create-wizard auto-created it).
  'vision:analysis_complete': {
    handler: async (payload) => {
      const productStore = useProductStore()
      const notificationStore = useNotificationStore()

      // FE-9166: the store refresh must never swallow the notification or the
      // window-event dispatch below — if a fetch rejects, the wizard's
      // 'vision-analysis-complete' listener would never fire and it would stay
      // stuck on "Analyzing". Warn and press on.
      if (payload?.product_id) {
        try {
          await productStore.fetchProducts()
          await productStore.fetchProductById(payload.product_id)
        } catch (err) {
          console.warn('[systemEventRoutes] vision:analysis_complete store refresh failed:', err)
        }
      }

      notificationStore.addNotification({
        type: 'vision_analysis',
        title: 'Vision Analysis Complete',
        message: `AI populated ${payload?.fields_written || 0} product fields. Review in Product Info.`,
        metadata: { product_id: payload?.product_id, fields: payload?.fields },
      })

      dispatchWindowEvent('vision-analysis-complete', payload)
    },
  },

  // System update notifications. The banner's visibility is driven by the
  // notification rows the backend emits (see SystemStatusBanner.vue); there is
  // no client re-fetch on this event. This handler only surfaces an
  // informational "updates available" item in the bell-icon badge.
  'system:update_available': {
    handler: async (payload) => {
      dispatchWindowEvent('ws-system-update-available', payload)

      const notificationStore = useNotificationStore()
      notificationStore.addNotification({
        type: 'system_alert',
        title: 'Updates available',
        message:
          'Server updates available. Run `git pull`, then restart your server. Migrations apply automatically.',
        metadata: payload ?? {},
      })
    },
  },

  // Tasks (MCP tool creates — frontend needs refresh)
  'task:created': {
    handler: async () => {
      const taskStore = useTaskStore()
      await taskStore.fetchTasks()
    },
  },

  // Tasks (REST status change / MCP update — FE-9274 P2, same class as BE-9246:
  // the backend now broadcasts this on PATCH /tasks/{id}/status/ and update_task,
  // but nothing repainted the list until this route existed).
  'task:updated': {
    handler: async () => {
      const taskStore = useTaskStore()
      await taskStore.fetchTasks()
    },
  },

  // Template updates (enable/disable, field changes) — dispatch to TemplateManager
  'template:updated': {
    handler: async (payload) => {
      dispatchWindowEvent('template:updated', payload)
    },
  },

  // Agent setup events. Drift state is computed server-side from the bundled
  // SKILLS_VERSION vs system_settings.skills_version_announced, so these
  // handlers only re-dispatch for downstream listeners.
  'setup:agents_downloaded': {
    handler: async (payload) => {
      dispatchWindowEvent('setup:agents_downloaded', payload)
    },
  },

  'setup:bootstrap_complete': {
    handler: async (payload) => {
      dispatchWindowEvent('setup:bootstrap_complete', payload)
    },
  },
}
