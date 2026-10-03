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
    if (threadPostCount.value > 0) keys.push('thread-post')
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
