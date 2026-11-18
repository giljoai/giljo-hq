import { onBeforeUnmount, ref } from 'vue'

import { useClipboard } from '@/composables/useClipboard'
import { SETUP_REQUEST } from '@/content/onboarding/guide'

const COPIED_MS = 2000

export function useSetupRequestCopy() {
  const { copy } = useClipboard()
  const copied = ref(false)
  let timer = null

  async function copyRequest() {
    const ok = await copy(SETUP_REQUEST)
    clearTimeout(timer)
    copied.value = ok
    if (ok) timer = setTimeout(() => (copied.value = false), COPIED_MS)
  }

  onBeforeUnmount(() => clearTimeout(timer))

  return { copied, copyRequest }
}
