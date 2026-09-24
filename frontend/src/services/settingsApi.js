import { apiClient } from './api.js'

export const executionModeDefaultApi = {
  getExecutionModeDefault: () => apiClient.get('/api/v1/settings/execution-mode-default'),
  updateExecutionModeDefault: (choice) =>
    apiClient.put('/api/v1/settings/execution-mode-default', { execution_mode_default: choice }),
}

export const handoverTemplateApi = {
  getHandoverTemplate: () => apiClient.get('/api/v1/settings/handover-template'),
  updateHandoverTemplate: (text) =>
    apiClient.put('/api/v1/settings/handover-template', { handover_template: text }),
  resetHandoverTemplate: () => apiClient.post('/api/v1/settings/handover-template/reset'),
}
