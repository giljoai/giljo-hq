import { apiClient } from './api.js'

export const executionModeDefaultApi = {
  getExecutionModeDefault: () => apiClient.get('/api/v1/settings/execution-mode-default'),
  updateExecutionModeDefault: (choice) =>
    apiClient.put('/api/v1/settings/execution-mode-default', { execution_mode_default: choice }),
}
