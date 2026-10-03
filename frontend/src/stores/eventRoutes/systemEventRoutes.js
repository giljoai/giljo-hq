import { useAgentJobsStore } from '../agentJobsStore'
import { useNotificationStore } from '../notifications'
import { useProductStore } from '../products'
import { useTaskStore } from '../tasks'
import { useMemoryStore } from '../memoryStore'

function dispatchWindowEvent(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

export const SYSTEM_EVENT_ROUTES = {
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

  'product:memory:updated': {
    handler: async (payload, { storeRegistry } = {}) => {
      const memoryStore = storeRegistry?.memory?.() ?? useMemoryStore()
      memoryStore.handleMemoryEntryWritten(payload?.product_id, payload?.entry)
    },
  },
  'product:status:changed': { store: 'products', action: 'handleProductStatusChanged' },

  'product:created': {
    handler: async (_payload, { storeRegistry } = {}) => {
      const productStore = storeRegistry?.products?.() ?? useProductStore()
      try {
        await productStore.fetchProducts()
      } catch (err) {
        console.warn('[systemEventRoutes] product:created store refresh failed:', err)
      }
    },
  },

  'product:updated': {
    handler: async (payload, { storeRegistry } = {}) => {
      const productStore = storeRegistry?.products?.() ?? useProductStore()
      try {
        await Promise.all([
          productStore.fetchProducts(),
          payload?.product_id ? productStore.fetchProductById(payload.product_id) : Promise.resolve(),
        ])
      } catch (err) {
        console.warn('[systemEventRoutes] product:updated store refresh failed:', err)
      }
    },
  },

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

  'vision:analysis_started': {
    handler: async (payload) => {
      dispatchWindowEvent('vision-analysis-started', payload)
    },
  },

  'vision:analysis_complete': {
    handler: async (payload) => {
      const productStore = useProductStore()
      const notificationStore = useNotificationStore()

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

  'project:memory_updated': {
    handler: async (payload) => {
      dispatchWindowEvent('project:memory_updated', payload)
    },
  },

  'task:created': {
    handler: async () => {
      const taskStore = useTaskStore()
      await taskStore.refreshList()
    },
  },

  'task:updated': {
    handler: async () => {
      const taskStore = useTaskStore()
      await taskStore.refreshList()
    },
  },

  'template:updated': {
    handler: async (payload) => {
      dispatchWindowEvent('template:updated', payload)
    },
  },

  'setup:bootstrap_complete': {
    handler: async (payload) => {
      dispatchWindowEvent('setup:bootstrap_complete', payload)
    },
  },
}
