import { apiClient } from './api.js'

export const promptsApi = {
  staging: (projectId, params) =>
    apiClient.get(`/api/v1/prompts/staging/${projectId}`, { params }),
  agentPrompt: (agentJobId) => apiClient.get(`/api/v1/prompts/agent/${agentJobId}`),
  implementation: (projectId) => apiClient.get(`/api/v1/prompts/implementation/${projectId}`),
  chainStaging: (runId) => apiClient.get(`/api/v1/prompts/chain-staging/${runId}`),
  chainImplementation: (runId) => apiClient.get(`/api/v1/prompts/chain-implementation/${runId}`),
  chainMember: (projectId) => apiClient.get(`/api/v1/prompts/chain-member/${projectId}`),
  chainMemberFallback: (projectId) =>
    apiClient.get(`/api/v1/prompts/chain-member/${projectId}`, { params: { fallback: true } }),
}
