import { ref } from 'vue'

const toasts = ref([])
let toastId = 0

export function useToast() {
  const showToast = (options) => {
    const id = ++toastId
    const toast = {
      id,
      show: true,
      ...options,
    }

    toasts.value.push(toast)

    if (window.$toast?.show) {
      window.$toast.show(options)
    } else {
      window.dispatchEvent(new CustomEvent('show-toast', { detail: options }))
    }

    return id
  }

  const hideToast = (id) => {
    const index = toasts.value.findIndex((toast) => toast.id === id)
    if (index > -1) {
      toasts.value[index].show = false
    }
  }

  const removeToast = (id) => {
    const index = toasts.value.findIndex((toast) => toast.id === id)
    if (index > -1) {
      toasts.value.splice(index, 1)
    }
  }

  return {
    toasts,
    showToast,
    hideToast,
    removeToast,
  }
}
