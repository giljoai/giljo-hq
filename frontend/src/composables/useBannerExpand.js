import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

const INTERACTIVE = 'button, a, input, select, textarea, [role="button"], [role="link"]'

export function useBannerExpand(textSource) {
  const messageEl = ref(null)
  const messageId = `banner-msg-${useId()}`
  const expanded = ref(false)
  const truncated = ref(false)
  let observer = null

  function measure() {
    const el = messageEl.value
    if (!el || expanded.value) return
    truncated.value = el.scrollWidth > el.clientWidth
  }

  const expandable = computed(() => expanded.value || truncated.value)

  function toggle() {
    if (!expandable.value) return
    expanded.value = !expanded.value
    if (!expanded.value) nextTick(measure)
  }

  function onBarClick(event) {
    if (event?.target?.closest?.(INTERACTIVE)) return
    const selection = window.getSelection?.()
    if (selection?.toString() && event.currentTarget?.contains?.(selection.anchorNode)) return
    toggle()
  }

  function onTextClick(event) {
    if (!expandable.value) return
    event?.stopPropagation?.()
    onBarClick(event)
  }

  watch(
    messageEl,
    (el, prev) => {
      if (prev && observer) observer.unobserve(prev)
      if (!el) {
        expanded.value = false
        truncated.value = false
        return
      }
      if (!observer && typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(() => measure())
      }
      observer?.observe(el)
      measure()
    },
    { flush: 'post' },
  )

  if (textSource) {
    watch(textSource, () => nextTick(measure))
  }

  onBeforeUnmount(() => observer?.disconnect())

  return { messageEl, messageId, expanded, expandable, toggle, onBarClick, onTextClick }
}
