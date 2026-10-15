import { useCommHubStore } from '@/stores/commHubStore'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'

const DONE_STATUSES = new Set(['resolved', 'closed'])
const RESOLVED = 'resolved'
const REOPENED = 'open'

function isThreadDone(status) {
  return DONE_STATUSES.has(String(status || '').toLowerCase())
}

export function threadResolveControl(status) {
  return isThreadDone(status)
    ? { label: 'Reopen', icon: 'mdi-undo' }
    : { label: 'Mark resolved', icon: 'mdi-check-circle-outline' }
}

const inFlight = new Set()

export function useThreadResolve() {
  const commHub = useCommHubStore()
  const { showToast } = useToast()

  async function apply(id, status) {
    if (inFlight.has(id)) return false
    inFlight.add(id)
    try {
      await commHub.setThreadStatus(id, status)
      return true
    } catch (err) {
      const msg = parseErrorResponse(err).message || 'Could not change this thread.'
      showToast({ type: 'error', message: msg })
      return false
    } finally {
      inFlight.delete(id)
    }
  }

  async function toggleResolved(thread) {
    const id = thread?.thread_id
    if (!id) return
    const previous = thread.status || REOPENED
    const reopening = isThreadDone(previous)
    if (!(await apply(id, reopening ? REOPENED : RESOLVED))) return
    showToast({
      type: 'success',
      message: reopening ? 'Thread reopened.' : 'Thread resolved.',
      action: { label: 'Undo', callback: () => apply(id, previous) },
    })
  }

  return { toggleResolved }
}
