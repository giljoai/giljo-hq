import { useAgentJobsStore } from '../agentJobsStore'
import { useNotificationStore } from '../notifications'
import { useApprovalsStore } from '../useApprovalsStore'


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
          // eslint-disable-next-line no-console
          console.debug('[agentEventRoutes] approvals handleStatusEvent failed:', err?.message)
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
      agentJobsStore.removeJob?.(payload?.agent_id || payload?.job_id)
    },
  },
  'agent:mission_updated': { store: 'agentJobs', action: 'handleUpdated' },
  'job:mission_updated': { store: 'agentJobs', action: 'handleMissionLengthUpdated' },
  'agent:health_alert': {
    handler: async (payload) => {
      const {
        health_state,
        agent_display_name,
        issue_description,
        job_id,
        project_name,
        project_id,
        execution_id,
      } = payload

      if (health_state === 'critical' || health_state === 'timeout') {
        const prefix = project_name ? `[${project_name}] ` : ''
        const notificationStore = useNotificationStore()
        notificationStore.addNotification({
          type: 'agent_health',
          title: 'Agent Health Alert',
          message: `${prefix}${agent_display_name} - ${issue_description}`,
          metadata: {
            job_id,
            agent_display_name,
            health_state,
            project_id,
            project_name,
            execution_id,
          },
        })
      }
    },
  },
  'agent:silent': {
    handler: async (payload, { storeRegistry } = {}) => {
      const { agent_display_name, reason, job_id, project_name, project_id, execution_id } = payload

      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()
      agentJobsStore.handleStatusChanged({
        job_id,
        status: 'silent',
        project_id,
        agent_display_name,
        execution_id,
      })

      const prefix = project_name ? `[${project_name}] ` : ''
      const notificationStore = useNotificationStore()
      notificationStore.addNotification({
        type: 'agent_health',
        title: 'Agent Silent',
        message: `${prefix}${agent_display_name} - ${reason || 'Agent stopped communicating'}`,
        metadata: {
          job_id,
          agent_display_name,
          reason,
          project_id,
          project_name,
          execution_id,
        },
      })
    },
  },

  'agent:auto_failed': {
    handler: async (payload) => {
      const { agent_display_name, reason, job_id, project_name, project_id, execution_id } = payload

      const prefix = project_name ? `[${project_name}] ` : ''
      const notificationStore = useNotificationStore()
      notificationStore.addNotification({
        type: 'agent_health',
        title: 'Agent Auto-Failed',
        message: `${prefix}${agent_display_name} - ${reason || 'Agent auto-failed'}`,
        metadata: {
          job_id,
          agent_display_name,
          reason,
          project_id,
          project_name,
          execution_id,
        },
      })
    },
  },

  'orchestrator:handover_initiated': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()
      agentJobsStore.handleStatusChanged?.({
        job_id: payload?.job_id,
        agent_id: payload?.agent_id,
        status: 'handed_over',
        project_id: payload?.project_id,
      })
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
