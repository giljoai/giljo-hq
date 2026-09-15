
const MIN_VISIBLE_PX = 50

function getClientPosition(event) {
  if (event.clientX !== undefined && event.clientY !== undefined) {
    return { x: event.clientX, y: event.clientY }
  }
  if (event.touches && event.touches.length > 0) {
    return { x: event.touches[0].clientX, y: event.touches[0].clientY }
  }
  return null
}

function isInsideFullscreenDialog(el) {
  const dialog = el.closest('.v-dialog')
  return dialog !== null && dialog.classList.contains('v-dialog--fullscreen')
}

export const draggable = {
  mounted(el) {
    const handle = el.querySelector('.dlg-header') || el.querySelector('.v-card-title')
    if (!handle) return

    if (isInsideFullscreenDialog(el)) return

    let isDragging = false
    let startX = 0
    let startY = 0
    let offsetX = 0
    let offsetY = 0

    handle.style.cursor = 'move'
    handle.style.userSelect = 'none'

    function onPointerDown(event) {
      if (isInsideFullscreenDialog(el)) return

      const pos = getClientPosition(event)
      if (!pos) return

      isDragging = true
      startX = pos.x - offsetX
      startY = pos.y - offsetY
      handle.style.cursor = 'grabbing'
      event.preventDefault()
    }

    function onPointerMove(event) {
      if (!isDragging) return

      const pos = getClientPosition(event)
      if (!pos) return

      let newX = pos.x - startX
      let newY = pos.y - startY

      const rect = el.getBoundingClientRect()
      const deltaX = newX - offsetX
      const deltaY = newY - offsetY

      const projectedLeft = rect.left + deltaX
      const projectedTop = rect.top + deltaY
      const projectedRight = projectedLeft + rect.width
      const projectedBottom = projectedTop + rect.height

      if (projectedRight < MIN_VISIBLE_PX) {
        newX = offsetX
      }
      if (projectedLeft > window.innerWidth - MIN_VISIBLE_PX) {
        newX = offsetX
      }
      if (projectedBottom < MIN_VISIBLE_PX) {
        newY = offsetY
      }
      if (projectedTop > window.innerHeight - MIN_VISIBLE_PX) {
        newY = offsetY
      }

      offsetX = newX
      offsetY = newY
      el.style.transform = `translate(${offsetX}px, ${offsetY}px)`
    }

    function onPointerUp() {
      if (!isDragging) return
      isDragging = false
      handle.style.cursor = 'move'
    }

    handle.addEventListener('mousedown', onPointerDown)
    document.addEventListener('mousemove', onPointerMove)
    document.addEventListener('mouseup', onPointerUp)

    handle.addEventListener('touchstart', onPointerDown, { passive: false })
    document.addEventListener('touchmove', onPointerMove, { passive: false })
    document.addEventListener('touchend', onPointerUp)

    el._draggableCleanup = () => {
      handle.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('mousemove', onPointerMove)
      document.removeEventListener('mouseup', onPointerUp)
      handle.removeEventListener('touchstart', onPointerDown)
      document.removeEventListener('touchmove', onPointerMove)
      document.removeEventListener('touchend', onPointerUp)
      el.style.transform = ''
    }
  },

  unmounted(el) {
    if (el._draggableCleanup) {
      el._draggableCleanup()
      delete el._draggableCleanup
    }
  },
}
