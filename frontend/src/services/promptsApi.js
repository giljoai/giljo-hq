/**
 * Prompts API — every ready-to-paste prompt surface (FE-9555).
 *
 * Extracted from api.js for the reason sequenceRunsApi.js was: that file sits on
 * the 800-line CI guardrail, and adding the FE-9555 master-prompt call pushed it
 * over. Moving the whole `prompts` family rather than only the new line keeps one
 * concept in one place instead of splitting it across two modules to save four
 * lines.
 *
 * Edition scope: Both.
 */
import { apiClient } from './api.js'

export const promptsApi = {
  staging: (projectId, params) =>
    apiClient.get(`/api/v1/prompts/staging/${projectId}`, { params }),
  agentPrompt: (agentJobId) => apiClient.get(`/api/v1/prompts/agent/${agentJobId}`),
  // Handover 0344: CLI mode implementation prompt for orchestrator play button
  implementation: (projectId) => apiClient.get(`/api/v1/prompts/implementation/${projectId}`),
  // Handover 0498: Termination prompt for early project shutdown
  termination: (projectId) => apiClient.get(`/api/v1/prompts/termination/${projectId}`),
  // FE-6165f: chain (sequence-run-scoped) kickoff prompts. RUN-scoped (run_id),
  // distinct from the project-scoped staging/implementation above. BE-6165d
  // returns ChainPromptResponse { run_id, head_project_id, orchestrator_job_id,
  // prompt }; the Stage Chain / Implement Chain buttons copy `data.prompt`.
  chainStaging: (runId) => apiClient.get(`/api/v1/prompts/chain-staging/${runId}`),
  chainImplementation: (runId) => apiClient.get(`/api/v1/prompts/chain-implementation/${runId}`),
  // FE-9555: the board-level "Launch staged..." master prompt. SELECTION-scoped
  // (project_ids), so unlike chainStaging above it needs no run to exist yet --
  // the pasted session creates the run itself via link_projects.
  buildMasterPrompt: (body) => apiClient.post('/api/v1/prompts/master', body),
}
