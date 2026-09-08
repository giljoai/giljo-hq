/**
 * agentDisplay.js — shared row-level display helpers
 *
 * Lifted from JobsTab (FE-6042a) so both JobsTab and AgentRow can share
 * the `isOrchestrator` predicate without duplication.
 *
 * Edition scope: CE
 */

import { getAgentColor, getAgentColorKey } from '@/config/agentColors'

/**
 * Returns true when the agent is the orchestrator role.
 * @param {Object|null} agent
 * @returns {boolean}
 */
export function isOrchestrator(agent) {
  return agent?.agent_name === 'orchestrator' || agent?.agent_display_name === 'orchestrator'
}

/**
 * FE-9548 (lifted from AgentRow.vue's local getPrimaryAgentLabel, verbatim,
 * so the wide JobsTab row and the compact Jobs-board row agree on what an
 * agent's primary label is): the orchestrator shows its agent_name (falling
 * back to agent_display_name); every other agent shows its agent_display_name
 * (falling back to agent_name).
 *
 * @param {Object|null} agent
 * @returns {string}
 */
export function getPrimaryAgentLabel(agent) {
  if (!agent) return ''
  if (isOrchestrator(agent)) return agent.agent_name || agent.agent_display_name || ''
  return agent.agent_display_name || agent.agent_name || ''
}

/**
 * FE-9548: a short, human role label for an agent -- "Implementer",
 * "Tester", "Reviewer", etc., or "Fixed System Agent" for the orchestrator
 * (matching AgentRow's existing "Skills: Fixed system agent" convention).
 * Derived from the SAME canonical color key getAgentColor() already resolves
 * (getAgentColorKey + AGENT_COLORS[...].name), title-cased for display --
 * not a second role taxonomy, just a readable form of the one that already
 * decides badge color.
 *
 * @param {Object|null} agent
 * @returns {string}
 */
export function getAgentRoleLabel(agent) {
  if (isOrchestrator(agent)) return 'Fixed System Agent'
  const key = getAgentColorKey(agent) || agent?.agent_display_name || ''
  const name = getAgentColor(key)?.name || ''
  if (!name) return ''
  return name.charAt(0) + name.slice(1).toLowerCase()
}
