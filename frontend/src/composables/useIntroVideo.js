import { computed, ref, watch } from 'vue'

import { useBannerDismissStore } from '@/stores/bannerDismissStore'
import { useUserStore } from '@/stores/user'

export const INTRO_VIDEO_STALL_MS = 20000
const INTRO_VIDEO_LINK_DAYS = 30
export const INTRO_VIDEO_RELEASED_AT = '2026-11-15T00:00:00Z'

const SAVE_PENDING_KEY = 'intro-video:save-pending'
const DAY_MS = 24 * 60 * 60 * 1000

function createdAtMs(createdAt) {
  if (!createdAt) return null
  const ms = Date.parse(createdAt)
  return Number.isNaN(ms) ? null : ms
}

export function isFirstThirtyDays(createdAt, now = Date.now()) {
  const ms = createdAtMs(createdAt)
  if (ms === null) return false
  return now - ms < INTRO_VIDEO_LINK_DAYS * DAY_MS
}

export function isPreReleaseAccount(createdAt) {
  const ms = createdAtMs(createdAt)
  return ms !== null && ms < Date.parse(INTRO_VIDEO_RELEASED_AT)
}

export function isPostReleaseAccount(createdAt) {
  const ms = createdAtMs(createdAt)
  return ms !== null && ms >= Date.parse(INTRO_VIDEO_RELEASED_AT)
}

const closedForUserId = ref(null)

export function useIntroVideoPending() {
  const userStore = useUserStore()
  const marks = useBannerDismissStore()
  return computed(() => {
    const user = userStore.currentUser
    return (
      user?.intro_video_seen === false &&
      closedForUserId.value !== user.id &&
      !marks.isDismissed(SAVE_PENDING_KEY)
    )
  })
}

export function useIntroVideo() {
  const userStore = useUserStore()
  const marks = useBannerDismissStore()
  const pending = useIntroVideoPending()

  async function save() {
    try {
      await userStore.updateSetupState({ intro_video_seen: true })
      marks.undismiss(SAVE_PENDING_KEY)
      return true
    } catch (error) {
      console.warn('[IntroVideo] Could not save that the video was watched:', error?.message)
      return false
    }
  }

  async function markSeen() {
    closedForUserId.value = userStore.currentUser?.id ?? null
    const saved = await save()
    if (!saved) marks.dismiss(SAVE_PENDING_KEY)
    return saved
  }

  let retriedFor = null
  watch(
    () => [userStore.currentUser?.id, userStore.currentUser?.intro_video_seen],
    ([id, seen]) => {
      if (!id || seen !== false || retriedFor === id || !marks.isDismissed(SAVE_PENDING_KEY)) return
      retriedFor = id
      save()
    },
    { immediate: true },
  )

  return { pending, markSeen }
}
