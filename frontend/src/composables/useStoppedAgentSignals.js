import { reactive } from 'vue'

import { useUserStore } from '@/stores/user'
import { useProjectStore } from '@/stores/projects'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { isOrchestrator } from '@/utils/agentDisplay'
import { decisionRouteFor, projectRouteFor } from '@/components/navigation/notificationRouting'

export const DECISION_FOCUS = 'decision'
export const BLOCKED_FOCUS = 'blocked'
export const SILENT_FOCUS = 'silent'

export const ALL_SCOPE_ONLY_REASONS = new Set([SILENT_FOCUS])

const BODY_MAX_CHARS = 120

const live = reactive({
  [DECISION_FOCUS]: new Map(),
  [BLOCKED_FOCUS]: new Map(),
  [SILENT_FOCUS]: new Map(),
})

export function liveStoppedAgentKeys() {
  const out = []
  for (const reason of [DECISION_FOCUS, BLOCKED_FOCUS, SILENT_FOCUS]) {
    for (const key of live[reason].keys()) out.push({ reason, key })
  }
  return out
}

function decisionKey(payload) {
  return payload.project_id || payload.job_id
}

function isSameTenant(payload) {
  const currentTenantKey = useUserStore().currentUser?.tenant_key
  if (!currentTenantKey || !payload?.tenant_key) return true
  return payload.tenant_key === currentTenantKey
}

function truncate(text, max) {
  const trimmed = typeof text === 'string' ? text.trim() : ''
  if (trimmed.length <= max) return trimmed
  return `${trimmed.slice(0, max - 3).trimEnd()}...`
}

function titled(label, projectName) {
  return projectName ? `${label}: ${projectName}` : label
}

async function resolveProject(projectId) {
  if (!projectId) return { name: null, implementing: null }
  const projects = useProjectStore()
  const states = useProjectStateStore()

  const read = () => {
    const entity = projects.projectById(projectId)
    const state = states.getProjectState(projectId)
    const implementing = state
      ? Boolean(state.implementationLaunched)
      : entity
        ? Boolean(entity.implementation_launched_at)
        : null
    return { name: entity?.name || null, implementing, known: Boolean(entity || state) }
  }

  let found = read()
  if (!found.known) {
    try {
      await projects.fetchProject(projectId)
    } catch {
      // Unknown stays unknown; the callers fail closed on it.
    }
    found = read()
  }
  return { name: found.name, implementing: found.implementing }
}

function routeFor(projectId) {
  return projectId ? projectRouteFor({ project_id: projectId }) : { name: 'JobsViewport' }
}

export function useStoppedAgentSignals({ fire, navigate }) {
  function raise(reason, key, title, body, route) {
    if (!document.hidden) return
    live[reason].set(key, true)
    fire(title, body, key, { reason, onClick: () => navigate(route) })
  }

  function clear(reason, key) {
    live[reason].delete(key)
  }

  async function onStatusChanged(payload) {
    const jobId = payload?.job_id
    if (!jobId || !isSameTenant(payload)) return
    const status = payload.status

    if (status !== 'blocked') clear(BLOCKED_FOCUS, jobId)
    if (status !== 'silent') clear(SILENT_FOCUS, jobId)

    if (payload.decided_option_id) {
      clear(DECISION_FOCUS, decisionKey(payload))
      return
    }

    if (status === 'awaiting_user' && payload.user_approval_id) {
      const key = decisionKey(payload)
      if (live[DECISION_FOCUS].has(key) || !document.hidden) return
      const { name } = await resolveProject(payload.project_id)
      const who = payload.agent_display_name || 'An agent'
      raise(
        DECISION_FOCUS,
        key,
        titled('Decision needed', name),
        `${who} is waiting for your answer`,
        payload.project_id ? decisionRouteFor(payload.project_id) : { name: 'JobsViewport' },
      )
      return
    }

    if (status === 'blocked') {
      if (live[BLOCKED_FOCUS].has(jobId) || !document.hidden) return
      const { name } = await resolveProject(payload.project_id)
      const who = payload.agent_display_name || 'An agent'
      raise(
        BLOCKED_FOCUS,
        jobId,
        titled(`${who} is blocked`, name),
        truncate(payload.block_reason, BODY_MAX_CHARS) || 'The agent is waiting on you',
        routeFor(payload.project_id),
      )
    }
  }

  async function onSilent(payload) {
    const jobId = payload?.job_id
    if (!jobId || !isSameTenant(payload) || !isOrchestrator(payload)) return
    if (live[SILENT_FOCUS].has(jobId) || !document.hidden) return

    const { name, implementing } = await resolveProject(payload.project_id)
    if (implementing !== true) return

    raise(
      SILENT_FOCUS,
      jobId,
      titled('Orchestrator gone silent', name),
      truncate(payload.reason, BODY_MAX_CHARS) || 'The orchestrator has stopped reporting',
      routeFor(payload.project_id),
    )
  }

  function onProgress(payload) {
    const jobId = payload?.job_id
    if (!jobId) return
    clear(BLOCKED_FOCUS, jobId)
    clear(SILENT_FOCUS, jobId)
  }

  const guarded = (handler) => (event) =>
    Promise.resolve()
      .then(() => handler(event?.detail || {}))
      .catch((error) => {
        console.warn('[useStoppedAgentSignals] signal handling failed:', error)
      })

  const listeners = [
    ['agent:status_changed', guarded(onStatusChanged)],
    ['agent:silent', guarded(onSilent)],
    ['job:progress_update', guarded(onProgress)],
  ]

  if (typeof window !== 'undefined') {
    for (const [type, listener] of listeners) window.addEventListener(type, listener)
  }

  return {
    dispose: () => {
      if (typeof window === 'undefined') return
      for (const [type, listener] of listeners) window.removeEventListener(type, listener)
    },
  }
}
