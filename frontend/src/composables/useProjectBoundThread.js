import { useCommHubStore } from '@/stores/commHubStore'

export const BOUND_THREAD_MARKER_SUBJECT = '(project comms)'

function _pickBoundThread(candidates) {
  if (candidates.length === 0) return null
  if (candidates.length === 1) return candidates[0]
  const marked = candidates.find((t) => t.subject === BOUND_THREAD_MARKER_SUBJECT)
  if (marked) return marked
  return candidates.reduce((oldest, t) =>
    new Date(t.created_at) < new Date(oldest.created_at) ? t : oldest,
  )
}

export function useProjectBoundThread() {
  const commHub = useCommHubStore()

  async function resolveProjectThread(projectId) {
    await commHub.loadThreads({ project_id: projectId })
    const candidates = commHub.projectThreadList.filter((t) => t.project_id === projectId)
    const existing = _pickBoundThread(candidates)
    if (existing) return existing
    return commHub.createThread({ project_id: projectId, subject: BOUND_THREAD_MARKER_SUBJECT })
  }

  async function resolveExistingProjectThread(projectId) {
    await commHub.loadThreads({ project_id: projectId })
    return _pickBoundThread(commHub.projectThreadList.filter((t) => t.project_id === projectId))
  }

  return { resolveProjectThread, resolveExistingProjectThread }
}
