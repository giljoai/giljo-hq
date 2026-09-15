import api from '@/services/api'

import { createStatusesStore } from './createStatusesStore'

export const useTaskStatusesStore = createStatusesStore(
  'taskStatuses',
  () => api.taskStatuses.list(),
)
