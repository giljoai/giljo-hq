import { describe, it, expect, beforeEach } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ToastManager from './ToastManager.vue'
import { useSettingsStore } from '@/stores/settings'

const SnackbarStub = {
  name: 'VSnackbar',
  props: ['modelValue', 'timeout', 'color', 'location', 'minHeight'],
  template: '<div class="v-snackbar" :data-timeout="timeout"><slot /><slot name="actions" /></div>',
}

function mountManager() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(ToastManager, {
    global: { plugins: [pinia], stubs: { 'v-snackbar': SnackbarStub } },
  })
  return { wrapper, store: useSettingsStore() }
}

function timeouts(wrapper) {
  return wrapper.findAllComponents(SnackbarStub).map((s) => s.props('timeout'))
}

describe('ToastManager duration follows the notification settings', () => {
  beforeEach(() => localStorage.clear())

  it('a success toast and an error toast both close after the configured duration', async () => {
    const { wrapper, store } = mountManager()
    wrapper.vm.showToast({ message: 'Saved', type: 'success' })
    wrapper.vm.showToast({ message: 'Failed', type: 'error' })
    await wrapper.vm.$nextTick()

    expect(store.notificationDuration).toBe(5000)
    expect(timeouts(wrapper)).toEqual([5000, 5000])
  })

  it('a timeout passed by the caller does not override the configured duration', async () => {
    const { wrapper } = mountManager()
    wrapper.vm.showToast({ message: 'Copied', type: 'success', timeout: 1500 })
    wrapper.vm.showToast({ message: 'Stale', type: 'warning', timeout: 0 })
    await wrapper.vm.$nextTick()

    expect(timeouts(wrapper)).toEqual([5000, 5000])
  })

  it('changing the Display duration setting changes the toast timeout', async () => {
    const { wrapper, store } = mountManager()
    wrapper.vm.showToast({ message: 'Failed', type: 'error' })
    await store.updateSettings({ notifications: { position: 'bottom-right', duration: 9 } })
    wrapper.vm.showToast({ message: 'Saved', type: 'success' })
    await wrapper.vm.$nextTick()

    expect(timeouts(wrapper)).toEqual([9000, 9000])
  })
})

const SRC = join(__dirname, '..')
const SOURCE_FILE = /\.(vue|js|ts)$/
const SPEC_FILE = /\.spec\.(js|ts)$/
const TOAST_CALL = /(?:showToast|\btoast|\$toast\.\w+|new CustomEvent)\s*\(/g
const TIMEOUT_KEY = /\btimeout\s*[:,}]/

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path, out)
    else if (SOURCE_FILE.test(name) && !SPEC_FILE.test(name)) out.push(path)
  }
  return out
}

function callArguments(source, openIndex) {
  let depth = 1
  let i = openIndex
  while (i < source.length && depth) {
    if (source[i] === '(') depth++
    else if (source[i] === ')') depth--
    i++
  }
  return source.slice(openIndex, i - 1)
}

describe('no toast call picks its own duration', () => {
  it('no showToast, $toast or show-toast call under src/ passes a timeout', () => {
    const hits = []
    let callsSeen = 0
    for (const file of walk(SRC)) {
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(TOAST_CALL)) {
        const args = callArguments(source, match.index + match[0].length)
        if (match[0].startsWith('new CustomEvent') && !args.includes("'show-toast'")) continue
        callsSeen++
        if (TIMEOUT_KEY.test(args)) {
          hits.push(`${relative(SRC, file)}:${source.slice(0, match.index).split('\n').length}`)
        }
      }
    }
    expect(callsSeen).toBeGreaterThan(100)
    expect(hits).toEqual([])
  })
})
