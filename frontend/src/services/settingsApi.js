/**
 * Settings API — the account-level execution-mode default (FE-9555).
 *
 * Extracted from api.js for the same reason sequenceRunsApi.js was: that file
 * sits on the 800-line CI guardrail, so a new endpoint pair goes in its own
 * module and is spread onto `api.settings` rather than growing it.
 *
 * Edition scope: Both.
 */
import { apiClient } from './api.js'

export const executionModeDefaultApi = {
  // Staging refuses to pick a mode for a headless caller; this is the one place a
  // user says "stop asking, always do X" (ask every time / terminals / subagents).
  getExecutionModeDefault: () => apiClient.get('/api/v1/settings/execution-mode-default'),
  updateExecutionModeDefault: (choice) =>
    apiClient.put('/api/v1/settings/execution-mode-default', { execution_mode_default: choice }),
}
