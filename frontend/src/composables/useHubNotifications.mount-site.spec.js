/**
 * useHubNotifications.mount-site.spec.js — FE-9289c
 *
 * The handover bell must be mounted in EXACTLY ONE place. Its de-dupe set is
 * per-composable-instance, so a second mount (the obvious regression: someone
 * "adds it back" to HubView) would double-fire every toast and browser notification.
 *
 * This is a source-level guard rather than a runtime one because the failure is
 * structural — two call sites — and would otherwise only surface as a user seeing two
 * identical toasts. It asserts:
 *   - DefaultLayout mounts it (so the bell reaches the operator on any page), and
 *   - HubView does NOT (it moved out; re-adding it is the regression).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '..')

function callsUseHubNotifications(relPath) {
  const text = readFileSync(resolve(src, relPath), 'utf8')
  // A bare call `useHubNotifications()`, not merely the import or a comment mentioning it.
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
