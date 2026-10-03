export function useToast() {
  const showToast = (options) => {
    if (window.$toast?.show) {
      window.$toast.show(options)
    } else {
      window.dispatchEvent(new CustomEvent('show-toast', { detail: options }))
    }
  }

  return {
    showToast,
  }
}
