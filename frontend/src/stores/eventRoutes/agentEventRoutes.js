import { useAgentJobsStore } from '../agentJobsStore'
import { useNotificationStore } from '../notifications'
import { useApprovalsStore } from '../useApprovalsStore'

// FE-6174c: the mission-control roster patch (_patchMissionControlIfPresent) was
// removed with the retirement of Mission Control + missionControlStore. Agent
// events now flow only to agentJobsStore (the solo/jobs surface).

/**
 * Agent and orchestrator event route definitions.
 *
 * Each entry maps an event type to either:
 * - { store, action } for simple store dispatch
 * - { handler } for multi-store or complex logic
 */
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

      // FE-5017 Phase C: surface user_approval transitions to the inbox store.
      // Backend rides the existing 'agent:status_changed' channel — no new
      // event type — adding `user_approval_id` (on awaiting_user) and
      // `decided_option_id` (on resume) to the payload.
      if (payload?.user_approval_id || payload?.decided_option_id) {
        try {
          const approvalsStore = useApprovalsStore()
          await approvalsStore.handleStatusEvent(payload)
        } catch (err) {
          // Don't break the agent UI if the approvals store hiccups.
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
  // BE-6123: a never-run orchestrator fixture was hard-deleted on deactivate.
  // Drop the row live so a same-session deactivate->reactivate of the SAME
  // project doesn't leave a stale agent in the store (JobsTab only refetches
  // when projectId changes). The store keys agents by agent_id; removeJob
  // falls back to job_id when agent_id is absent.
  'agent:removed': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()
      agentJobsStore.removeJob?.(payload?.agent_id || payload?.job_id)
    },
  },
  'agent:mission_updated': { store: 'agentJobs', action: 'handleUpdated' },
  // D4 (Headless S3a): job:mission_updated (mission_service.py) fires on ANY job's
  // mission write (job_id/job_type/mission_length/project_id -- no display identity).
  // Distinct from its two confusably-named, already-wired neighbours: 'project:'
  // mission_updated (projectEventRoutes -> projectState.handleMissionUpdated) and
  // 'agent:mission_updated' immediately above. Routed to the existing-only
  // handleMissionLengthUpdated (not handleUpdated) -- see that action's comment.
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
        // Handover 0259: Include project context in health alert notifications
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
  // agent:silent is emitted by the silence detector (agent stopped communicating);
  // distinct from agent:auto_failed below, which the health monitor emits when it
  // auto-terminates an agent. Both are wired (FE-9151 restored the auto_failed route).
  'agent:silent': {
    handler: async (payload, { storeRegistry } = {}) => {
      const { agent_display_name, reason, job_id, project_name, project_id, execution_id } = payload

      // Update agent status in store so dashboard reflects silent state in real-time
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()
      agentJobsStore.handleStatusChanged({
        job_id,
        status: 'silent',
        project_id,
        agent_display_name,
        execution_id,
      })

      // Handover 0259: Include project context in silent agent notifications
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

  // FE-9151: the health monitor emits agent:auto_failed when it auto-terminates
  // an agent — abandoned past the hard ceiling (-> 'decommissioned') or a
  // timed-out agent with auto_fail_on_timeout (-> 'silent'). Before this route
  // the event reached no UI.
  //
  // FE-9151-FIX (option B): bell-only by design. This handler surfaces a bell
  // notification and deliberately does NOT write any status into agentJobsStore.
  // The card's status comes from the backend's real status ('decommissioned' or
  // 'silent') via the existing agent:status_changed path — both have proper
  // display configs. 'failed' is NOT a recognized display status (statusConfig.js
  // has no entry — product decision), so writing it would render gray "Unknown"
  // and mask the true status. The backend payload carries no project context, so
  // the project prefix is best-effort.
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

  // D12 (Headless S3a): orchestrator:handover_initiated (api/endpoints/agent_jobs/
  // simple_handover.py) fires when the retiring orchestrator's retirement +
  // continuation prompts are generated -- {agent_id, job_id, project_id, timestamp}.
  // Routed through the SAME existing-only handleStatusChanged used by
  // agent:status_changed above (no new store code, no relaxation of the
  // Handover 0462/0463 ghost-row guard): 'handed_over' is an already-configured
  // statusConfig.js status with no live writer today, exactly matching this event.
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
  // Handover 0431: Orchestrator prompt generated
  'orchestrator:prompt_generated': {
    handler: async (payload, { storeRegistry } = {}) => {
      const agentJobsStore = storeRegistry?.agentJobs?.() ?? useAgentJobsStore()

      // Handover 0700i: Removed instance_number
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
