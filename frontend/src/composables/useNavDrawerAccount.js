import { ref, computed, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { isCeModeValue } from '@/composables/useGiljoMode'

export function useNavDrawerAccount({ giljoMode }) {
  const router = useRouter()
  const { showToast } = useToast()

  const AccountStatusBadgeComponent = shallowRef(null)
  const accountStateStoreRef = shallowRef(null)

  const accountBadgeState = computed(() => accountStateStoreRef.value?.badgeState ?? 'none')
  const isAccountScheduledForDeletion = computed(
    () => accountStateStoreRef.value?.isAccountScheduledForDeletion ?? false,
  )

  const accountBadgeStateModifier = computed(() => {
    switch (accountBadgeState.value) {
      case 'account_scheduled_for_deletion':
        return 'danger'
      case 'trial_expired':
        return 'expired'
      case 'trial_ending_soon':
        return 'ending-soon'
      default:
        return 'none'
    }
  })

  const accountStatusTitle = computed(() => {
    switch (accountBadgeState.value) {
      case 'account_scheduled_for_deletion':
        return 'Account scheduled for deletion'
      case 'trial_expired':
        return 'Trial expired'
      case 'trial_ending_soon':
        return 'Trial ending soon'
      default:
        return ''
    }
  })

  const accountStatusSubtitle = computed(() => {
    const s = accountStateStoreRef.value
    if (!s) return ''
    switch (accountBadgeState.value) {
      case 'account_scheduled_for_deletion':
        return `Permanent purge on ${s.purgeAfterFormatted}.`
      case 'trial_expired':
        return 'Your workspace is read-only until you upgrade.'
      case 'trial_ending_soon': {
        const days = s.daysRemaining
        if (days === 0) return 'Trial ends today.'
        if (days === 1) return 'Trial ends in 1 day.'
        return `Trial ends in ${days} days.`
      }
      default:
        return ''
    }
  })

  const cancellingDeletion = ref(false)

  async function onCancelDeletion() {
    const store = accountStateStoreRef.value
    if (!store || cancellingDeletion.value) return
    cancellingDeletion.value = true
    try {
      await store.cancelDeletion()
      showToast({ message: 'Account deletion cancelled.', type: 'success' })
    } catch (err) {
      const detail = err?.response?.data?.detail
      showToast({
        message: detail || 'Could not cancel deletion. Please try again.',
        type: 'error',
      })
    } finally {
      cancellingDeletion.value = false
    }
  }

  function goUpgrade() {
    router.push('/billing')
  }

  async function loadAccountStateUI() {
    if (isCeModeValue(giljoMode.value)) return
    try {
      const badgeLoaders = import.meta.glob('@/saas/components/AccountStatusBadge.vue')
      const storeLoaders = import.meta.glob('@/saas/stores/useAccountStateStore.js')
      const [badgeLoader] = Object.values(badgeLoaders)
      const [storeLoader] = Object.values(storeLoaders)
      if (!badgeLoader || !storeLoader) return
      const [badgeMod, storeMod] = await Promise.all([badgeLoader(), storeLoader()])
      AccountStatusBadgeComponent.value = badgeMod.default
      accountStateStoreRef.value = storeMod.useAccountStateStore()
    } catch (err) {
      console.warn('[useNavDrawerAccount] Account-state UI unavailable:', err?.message)
    }
  }

  return {
    AccountStatusBadgeComponent,
    accountBadgeState,
    isAccountScheduledForDeletion,
    accountBadgeStateModifier,
    accountStatusTitle,
    accountStatusSubtitle,
    cancellingDeletion,
    onCancelDeletion,
    goUpgrade,
    loadAccountStateUI,
  }
}
