/**
 * useBannerFold.js — FE-9552
 *
 * The banner strip must never stack: this is the state machine behind that
 * rule, extracted out of SystemStatusBanner.vue (to keep that file within the project's file-size
 * cap) so a future strip needing the same "fold instead of stack" behaviour
 * (FE-9553's notification-model work is the named candidate) can reuse it
 * rather than reinvent it.
 *
 * Order: decision-needed (your-turn/approval/thread-post) > lifecycle > advisories
 * (system banners + the client-armed nudge rows). One key per rendered row -- a
 * multi-instance family (lifecycle, system banners) contributes one key per
 * instance, so the count and the ordering both stay accurate. Collapsed shows
 * only the FIRST key, which is a pure function of what is still live: acting
 * on or dismissing the current top removes it from its source array, which
 * removes its key here, which promotes the next one automatically -- no
 * pointer to advance by hand.
 */
import { ref, computed } from 'vue'

export function useBannerFold({
  yourTurnCount,
  approvalCount,
  threadPostCount,
  lifecycleRows,
  systemBanners,
  showTutorial,
  showInteg,
  showAgent,
}) {
  const bannerOrderKeys = computed(() => {
    const keys = []
    if (yourTurnCount.value > 0) keys.push('your-turn')
    if (approvalCount.value > 0) keys.push('approval')
    // FE-9586: thread-post signals (you were named, or an ask was directed at you).
    // Decision-needed class, so it sits with the baton and the raised hand rather
    // than among the advisories -- one row for both, never a stack.
    if ((threadPostCount?.value || 0) > 0) keys.push('thread-post')
    for (const row of lifecycleRows.value) keys.push(`lifecycle:${row.id}`)
    for (const n of systemBanners.value) keys.push(`system:${n.id}`)
    if (showTutorial.value) keys.push('tutorial')
    if (showInteg.value) keys.push('integ')
    if (showAgent.value) keys.push('agent')
    return keys
  })

  const totalBannerCount = computed(() => bannerOrderKeys.value.length)
  const foldExpanded = ref(false)
  const visibleBannerKeys = computed(() =>
    foldExpanded.value ? bannerOrderKeys.value : bannerOrderKeys.value.slice(0, 1),
  )

  function isBannerVisible(key) {
    return visibleBannerKeys.value.includes(key)
  }

  return { totalBannerCount, foldExpanded, visibleBannerKeys, isBannerVisible }
}
