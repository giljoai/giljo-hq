import { computed } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'

const TERMINAL = new Set(['resolved', 'closed'])

export function useYourTurnThreads() {
  const commHub = useCommHubStore()
  const userStore = useUserStore()

  const yourTurnThreads = computed(() => {
    const me = userStore.currentUser?.id
    if (!me) return []
    return commHub.threadList.filter(
      (t) =>
        t.next_action_owner === me && !TERMINAL.has(String(t.status || '').toLowerCase()),
    )
  })

  let requested = false
  async function ensureThreadsLoaded() {
    if (requested) return
    if (!userStore.currentUser?.id) return
    requested = true
    await commHub.loadThreads()
  }

  return { yourTurnThreads, ensureThreadsLoaded }
}
