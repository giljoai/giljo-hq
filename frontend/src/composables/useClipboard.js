
import { ref } from 'vue'

export function useClipboard() {
  const copied = ref(false)

  const copy = async (text) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
        copied.value = true
        setTimeout(() => (copied.value = false), 2000)
        return true
      }

      return fallbackCopy(text)
    } catch (err) {
      console.warn('[Clipboard] Primary method failed, using fallback:', err)
      return fallbackCopy(text)
    }
  }

  const fallbackCopy = (text) => {
    try {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', '')
      textarea.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0;pointer-events:none;'

      const overlays = document.querySelectorAll('.v-overlay--active .v-overlay__content')
      const container = overlays.length > 0 ? overlays[overlays.length - 1] : document.body
      container.appendChild(textarea)
      textarea.focus({ preventScroll: true })
      textarea.select()
      textarea.setSelectionRange(0, textarea.value.length)

      const successful = document.execCommand('copy')
      container.removeChild(textarea)

      if (successful) {
        copied.value = true
        setTimeout(() => (copied.value = false), 2000)
        return true
      }

      return false
    } catch (err) {
      console.error('[Clipboard] Fallback method failed:', err)
      return false
    }
  }

  return {
    copied,
    copy,
  }
}
