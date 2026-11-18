import { watch } from 'vue'

import { useGuideStore } from '@/stores/guide'
import { useStartListStore } from '@/stores/startList'
import { useUserStore } from '@/stores/user'

export function useSetupAutoSave() {
  const users = useUserStore()
  const list = useStartListStore()
  const guide = useGuideStore()
  let saved = false

  watch(
    [() => list.rows, () => guide.setupWizardOpen, () => users.currentUser?.id],
    async () => {
      const rows = list.rows
      const user = users.currentUser
      if (saved || !user || user.setup_complete || guide.setupWizardOpen || !rows) return
      if (!(rows.tool_connected.done && rows.skills_installed.done)) return
      saved = true
      try {
        await users.updateSetupState({ setup_complete: true })
      } catch {
        saved = false
      }
    },
    { immediate: true },
  )
}
