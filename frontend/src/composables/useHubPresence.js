import { ref, computed, onScopeDispose, getCurrentScope } from 'vue'
import { useRoute } from 'vue-router'

export function useHubPresence() {
  const route = useRoute()

  const isVisible = ref(
    typeof document !== 'undefined' ? document.visibilityState === 'visible' : false,
  )
  const isFocused = ref(typeof document !== 'undefined' ? document.hasFocus() : false)

  function onVisibilityChange() {
    isVisible.value = document.visibilityState === 'visible'
  }

  function onFocus() {
    isFocused.value = true
  }

  function onBlur() {
    isFocused.value = false
  }

  if (typeof window !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
    window.addEventListener('focus', onFocus)
    window.addEventListener('blur', onBlur)

    if (getCurrentScope()) {
      onScopeDispose(() => {
        document.removeEventListener('visibilitychange', onVisibilityChange)
        window.removeEventListener('focus', onFocus)
        window.removeEventListener('blur', onBlur)
      })
    }
  }

  const isHubPresent = computed(
    () => isVisible.value && isFocused.value && route.path === '/hub',
  )

  return { isHubPresent }
}
