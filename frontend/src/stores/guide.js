import { defineStore } from 'pinia'
import { computed, getCurrentScope, onScopeDispose, ref, watch } from 'vue'

import { buildGuideRows, NUDGE_AFTER_MS } from '@/content/onboarding/guide'
import { isPostReleaseAccount, useIntroVideoPending } from '@/composables/useIntroVideo'
import { useBannerDismissStore } from '@/stores/bannerDismissStore'
import { useStartListStore } from '@/stores/startList'
import { useUserStore } from '@/stores/user'

const FOLDED_KEY = 'guide:folded'
const TURNED_ON_KEY = 'guide:turned-on'
const CONNECT_OFFERED_KEY = 'guide:connect-offered'
const nudgeFiredKey = (n) => `guide:nudge-fired:${n}`
const nudgeEndedKey = (n) => `guide:nudge-ended:${n}`

export const useGuideStore = defineStore('guide', () => {
  const users = useUserStore()
  const list = useStartListStore()
  const marks = useBannerDismissStore()
  const introPending = useIntroVideoPending()

  const closedHere = ref(false)
  const latched = ref(false)
  const setupWizardOpen = ref(false)
  const reservedWidth = ref(0)

  const closed = computed(() => closedHere.value || users.currentUser?.guide_closed === true)
  const finished = computed(() => list.allDone && list.rows?.project_built?.done === true)
  const folded = computed(() => marks.isDismissed(FOLDED_KEY))

  const showsByItself = computed(
    () =>
      !!users.currentUser &&
      list.loaded &&
      !introPending.value &&
      !closed.value &&
      !finished.value &&
      isPostReleaseAccount(users.currentUser.created_at),
  )
  watch(showsByItself, (on) => {
    if (on) latched.value = true
  }, { immediate: true })

  const turnedOn = computed(() => marks.isDismissed(TURNED_ON_KEY))
  const visible = computed(
    () =>
      !!users.currentUser &&
      list.loaded &&
      !introPending.value &&
      !closed.value &&
      (turnedOn.value || latched.value),
  )

  function setReservedWidth(px) {
    reservedWidth.value = px
  }

  const currentRowN = computed(() => {
    if (!visible.value || finished.value || !list.rows) return null
    return buildGuideRows(list.rows).find((r) => r.current)?.n ?? null
  })
  const nudgedRow = computed(() => {
    const n = currentRowN.value
    return n !== null && marks.isDismissed(nudgeFiredKey(n)) && !marks.isDismissed(nudgeEndedKey(n)) ? n : null
  })

  function endNudge(n) {
    marks.dismiss(nudgeEndedKey(n))
  }

  let nudgeTimer = null
  let nudgeLeft = NUDGE_AFTER_MS
  let nudgeStartedAt = 0
  function stopNudgeTimer() {
    clearTimeout(nudgeTimer)
    nudgeTimer = null
  }
  function armNudgeTimer(ms) {
    stopNudgeTimer()
    nudgeStartedAt = Date.now()
    nudgeLeft = ms
    nudgeTimer = setTimeout(() => {
      nudgeTimer = null
      const n = currentRowN.value
      if (n !== null) marks.dismiss(nudgeFiredKey(n))
    }, ms)
  }
  function nudgeable(n) {
    return n !== null && !marks.isDismissed(nudgeFiredKey(n)) && !marks.isDismissed(nudgeEndedKey(n))
  }
  watch(
    currentRowN,
    (n) => {
      stopNudgeTimer()
      nudgeLeft = NUDGE_AFTER_MS
      if (nudgeable(n) && !document.hidden) armNudgeTimer(NUDGE_AFTER_MS)
    },
    { immediate: true },
  )
  function onVisibility() {
    if (document.hidden) {
      if (nudgeTimer) {
        nudgeLeft -= Date.now() - nudgeStartedAt
        stopNudgeTimer()
      }
    } else if (!nudgeTimer && nudgeable(currentRowN.value)) {
      armNudgeTimer(Math.max(nudgeLeft, 0))
    }
  }
  document.addEventListener('visibilitychange', onVisibility)
  if (getCurrentScope()) {
    onScopeDispose(() => {
      stopNudgeTimer()
      document.removeEventListener('visibilitychange', onVisibility)
    })
  }

  watch(
    () => (list.rows ? buildGuideRows(list.rows).filter((r) => r.state === 'done').map((r) => r.n) : []),
    (doneRows) => {
      for (const n of doneRows) if (marks.isDismissed(nudgeFiredKey(n))) endNudge(n)
    },
  )

  function setFolded(value) {
    if (value) marks.dismiss(FOLDED_KEY)
    else marks.undismiss(FOLDED_KEY)
  }

  async function close() {
    closedHere.value = true
    try {
      await users.updateSetupState({ guide_closed: true })
    } catch (error) {
      console.warn('[Guide] Could not save that the guide was closed:', error?.message)
    }
  }

  async function turnOn() {
    marks.dismiss(TURNED_ON_KEY)
    setFolded(false)
    closedHere.value = false
    try {
      await users.updateSetupState({ guide_closed: false })
    } catch (error) {
      console.warn('[Guide] Could not save that the guide is back on:', error?.message)
      return false
    }
    return true
  }

  async function offerConnectOnce(router) {
    if (marks.isDismissed(CONNECT_OFFERED_KEY)) return false
    await list.refresh({ force: true })
    if (!list.loaded || list.rows.tool_connected.done) return false
    marks.dismiss(CONNECT_OFFERED_KEY)
    router.push({ path: '/home', query: { openSetup: 'true' } })
    return true
  }

  return {
    visible,
    folded,
    closed,
    finished,
    setupWizardOpen,
    reservedWidth,
    nudgedRow,
    endNudge,
    setReservedWidth,
    setFolded,
    close,
    turnOn,
    offerConnectOnce,
  }
})
