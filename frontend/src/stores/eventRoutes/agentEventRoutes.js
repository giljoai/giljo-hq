import { useAgentJobsStore } from '../agentJobsStore'
import { useNotificationStore } from '../notifications'
import { useApprovalsStore } from '../useApprovalsStore'


function addAgentHealthNotice(title, text, payload, extra) {
  const { agent_display_name, job_id, project_name, project_id, execution_id } = payload
  const prefix = project_name ? `[${project_name}] ` : ''
  useNotificationStore().addNotification({
    type: 'agent_health',
    title,
    message: `${prefix}${agent_display_name} - ${text}`,
    metadata: { job_id, agent_display_name, ...extra, project_id, project_name, execution_id },
  })
}

export const AGENT_EVENT_ROUTES = {
  'agent:update': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()
      agentJobsStore.handleUpdated?.(payload)
    },
  },
  'agent:status_changed': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()
      agentJobsStore.handleStatusChanged?.(payload)

      if (payload?.user_approval_id || payload?.decided_option_id) {
        try {
          const approvalsStore = useApprovalsStore()
          await approvalsStore.handleStatusEvent(payload)
        } catch (err) {
          console.warn('[agentEventRoutes] approvals refresh failed:', err)
        }
      }
    },
  },
  'agent:created': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()

      const normalized = payload?.agent && typeof payload.agent === 'object'
        ? { ...payload.agent, project_id: payload.project_id, tenant_key: payload.tenant_key }
        : payload

      agentJobsStore.handleCreated?.(normalized)
    },
  },
  'agent:removed': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()
      agentJobsStore.removeJob(payload?.agent_id)
    },
  },
  'agent:mission_updated': { store: 'agentJobs', action: 'handleUpdated' },
  'job:mission_updated': { store: 'agentJobs', action: 'handleMissionLengthUpdated' },
  'agent:health_alert': {
    handler: async (payload) => {
      const { health_state, issue_description } = payload
      if (health_state === 'critical' || health_state === 'timeout') {
        addAgentHealthNotice('Agent Health Alert', issue_description, payload, { health_state })
      }
    },
  },
  'agent:silent': {
    handler: async (payload, { storeRegistry } = {}) => {
      const { agent_display_name, reason, job_id, project_id, execution_id } = payload

      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()
      agentJobsStore.handleStatusChanged({
        job_id,
        status: 'silent',
        project_id,
        agent_display_name,
        execution_id,
      })

      addAgentHealthNotice('Agent Silent', reason || 'Agent stopped communicating', payload, { reason })
    },
  },

  'agent:auto_failed': {
    handler: async (payload) => {
      const { reason } = payload
      addAgentHealthNotice('Agent Auto-Failed', reason || 'Agent auto-failed', payload, { reason })
    },
  },

  'orchestrator:prompt_generated': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()

      agentJobsStore.handleUpdated?.({
        job_id: payload.orchestrator_id,
        agent_id: payload.agent_id,
        execution_id: payload.execution_id,
        project_id: payload.project_id,
        agent_display_name: 'orchestrator',
        status: 'waiting',
        staged: true,
      })
    },
  },
}
