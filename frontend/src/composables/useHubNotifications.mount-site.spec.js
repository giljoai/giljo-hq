import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '..')

function callsUseHubNotifications(relPath) {
  const text = readFileSync(resolve(src, relPath), 'utf8')
  return /^\s*useHubNotifications\(\)/m.test(text)
}

describe('useHubNotifications mount site (FE-9289c)', () => {
  it('is mounted app-wide in DefaultLayout', () => {
    expect(callsUseHubNotifications('layouts/DefaultLayout.vue')).toBe(true)
  })

  it('is NOT mounted in HubView — it moved out and must not return', () => {
    expect(callsUseHubNotifications('views/HubView.vue')).toBe(false)
  })
})
