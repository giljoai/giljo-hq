import { computed } from 'vue'
import { hubThreadRoute } from '@/components/hub/hubThreadRoute'
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

const HUB_PATH = '/hub'

function waitingSince(thread) {
  const stamps = [thread?.last_activity_at, thread?.last_message?.created_at]
    .map((v) => (v ? new Date(v).getTime() : NaN))
    .filter((t) => !Number.isNaN(t))
  return stamps.length ? Math.max(...stamps) : Infinity
}

export function useYourTurnOpenNext({ router, threads }) {
  const commHub = useCommHubStore()

  const viewedThreadId = computed(() =>
    router.currentRoute?.value?.path === HUB_PATH ? commHub.selectedThreadId : null,
  )

  const openNextThreads = computed(() => {
    const byWait = [...threads.value].sort((a, b) => waitingSince(a) - waitingSince(b))
    const at = byWait.findIndex((t) => t.thread_id === viewedThreadId.value)
    if (at < 0) return byWait
    return [...byWait.slice(at + 1), ...byWait.slice(0, at)]
  })

  function openYourTurn() {
    const next = openNextThreads.value[0]
    if (next) router.push(hubThreadRoute(next))
  }

  return { openNextThreads, openYourTurn }
}
