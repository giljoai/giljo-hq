import api from '@/services/api'

import { createStatusesStore } from './createStatusesStore'

export const useProjectStatusesStore = createStatusesStore(
  'projectStatuses',
  () => api.projectStatuses.list(),
)
