import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useMarkHandled() {
  const commHub = useCommHubStore()
  const userStore = useUserStore()
  const route = useRoute()
  const router = useRouter()
  const { showToast } = useToast()

  const isYourTurn = computed(() => {
    const thread = commHub.selectedThread
    return thread?.next_action_owner != null && thread.next_action_owner === userStore.currentUser?.id
  })

  const clearing = ref(false)

  function clearFocusFromRoute() {
    const { focus, message, ...rest } = route.query
    if (focus === undefined && message === undefined) return
    router.replace({ path: route.path, query: rest })
  }

  async function markHandled() {
    const threadId = commHub.selectedThreadId
    if (!threadId || clearing.value) return
    clearing.value = true
    try {
      await commHub.passBaton(threadId, 'none')
      clearFocusFromRoute()
      showToast({ type: 'success', message: 'Handled — the turn is cleared.' })
    } catch (err) {
      const msg = parseErrorResponse(err).message || 'Could not clear the turn.'
      showToast({ type: 'error', message: msg })
    } finally {
      clearing.value = false
    }
  }

  return { isYourTurn, clearing, markHandled }
}
