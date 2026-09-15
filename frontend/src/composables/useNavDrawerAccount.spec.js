import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

describe('useNavDrawerAccount', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function makeComposable(overrides = {}) {
    const { useNavDrawerAccount } = await import('./useNavDrawerAccount')
    const giljoMode = ref(overrides.giljoMode ?? 'ce')
    return useNavDrawerAccount({ giljoMode })
  }

  it('accountBadgeState defaults to "none"', async () => {
    const { accountBadgeState } = await makeComposable()
    expect(accountBadgeState.value).toBe('none')
  })

  it('isAccountScheduledForDeletion defaults to false', async () => {
    const { isAccountScheduledForDeletion } = await makeComposable()
    expect(isAccountScheduledForDeletion.value).toBe(false)
  })

  it('accountBadgeStateModifier is "none" when badgeState is none', async () => {
    const { accountBadgeStateModifier } = await makeComposable()
    expect(accountBadgeStateModifier.value).toBe('none')
  })

  it('accountStatusTitle is empty string when badgeState is none', async () => {
    const { accountStatusTitle } = await makeComposable()
    expect(accountStatusTitle.value).toBe('')
  })

  it('AccountStatusBadgeComponent is null in CE mode', async () => {
    const { AccountStatusBadgeComponent } = await makeComposable({ giljoMode: 'ce' })
    expect(AccountStatusBadgeComponent.value).toBeNull()
  })

  it('exposes loadAccountStateUI function', async () => {
    const { loadAccountStateUI } = await makeComposable()
    expect(typeof loadAccountStateUI).toBe('function')
  })
})
