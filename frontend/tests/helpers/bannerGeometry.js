/**
 * SEC-0059h test helper: jsdom has no layout, so scrollWidth/clientWidth are
 * always 0. installBannerGeometry() answers those two reads ONLY for a banner's
 * one-line message element (class ending in __message or __text), from values
 * the test sets. It supplies geometry and nothing else: the decision "is this
 * cut off" stays the component's own comparison, which "equal widths" cases pin.
 * The ResizeObserver stub captures callbacks so a test can fire a resize.
 */
import { afterEach, beforeEach } from 'vitest'

const MESSAGE_CLASS = /__(message|text)\b/

export function installBannerGeometry() {
  const geometry = { scroll: 0, client: 0 }
  const observers = []
  let originalRO
  const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollWidth')
  const originalClient = Object.getOwnPropertyDescriptor(Element.prototype, 'clientWidth')
  const isMessage = (el) => typeof el.className === 'string' && MESSAGE_CLASS.test(el.className)

  beforeEach(() => {
    geometry.scroll = 0
    geometry.client = 0
    observers.length = 0
    originalRO = window.ResizeObserver
    window.ResizeObserver = class {
      constructor(cb) {
        this.cb = cb
        observers.push(this)
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    Object.defineProperty(Element.prototype, 'scrollWidth', {
      configurable: true,
      get() {
        return isMessage(this) ? geometry.scroll : 0
      },
    })
    Object.defineProperty(Element.prototype, 'clientWidth', {
      configurable: true,
      get() {
        return isMessage(this) ? geometry.client : 0
      },
    })
  })

  afterEach(() => {
    window.ResizeObserver = originalRO
    Object.defineProperty(Element.prototype, 'scrollWidth', originalScroll)
    Object.defineProperty(Element.prototype, 'clientWidth', originalClient)
  })

  return {
    /** Text needs `scroll` px; the element offers `client` px. */
    set(scroll, client) {
      geometry.scroll = scroll
      geometry.client = client
    },
    cut() {
      this.set(900, 200)
    },
    fits() {
      this.set(300, 300)
    },
    fireResize() {
      for (const o of observers) o.cb([])
    },
  }
}
