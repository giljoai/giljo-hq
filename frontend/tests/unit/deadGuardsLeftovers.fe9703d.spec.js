/**
 * Guards around values that are always present: the banner fold always gets
 * its thread-post count, ws.on always returns an unsubscribe function, and
 * checkEnhancedStatus always resolves.
 *
 * Edition scope: Both
 */
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { describe, it, expect } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWebSocketStore } from '@/stores/websocket'

const src = (p) => readFileSync(resolve(__dirname, '../../src', p), 'utf8')

describe('dead guards, leftovers', () => {
  it('ws.on returns an unsubscribe function, so the dashboard realtime hook calls it directly', () => {
    setActivePinia(createPinia())
    expect(typeof useWebSocketStore().on('x', () => {})).toBe('function')
    expect(src('composables/useDashboardRealtime.js')).not.toContain('unsub?.()')
  })

  it('the banner fold reads the thread-post count its one caller always passes', () => {
    expect(src('components/system/SystemStatusBanner.vue')).toContain('threadPostCount: computed(')
    expect(src('composables/useBannerFold.js')).not.toContain('threadPostCount?.value')
  })

  it('the account shell reads the edition without a catch around a call that never rejects', () => {
    expect(src('views/account/AccountShell.vue')).not.toContain('setupService error, defaulting to CE tabs')
  })
})
