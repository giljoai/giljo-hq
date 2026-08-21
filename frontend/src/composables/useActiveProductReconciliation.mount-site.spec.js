/**
 * useActiveProductReconciliation.mount-site.spec.js — FE-9412
 *
 * The backstop is only worth anything if it is actually mounted. Delete the
 * one line in DefaultLayout and every runtime spec still passes while no
 * session on earth re-validates its active product again — the exact
 * looks-installed-and-is-not failure this project exists to close.
 *
 * Source-level, following the FE-9289c mount-site guard precedent, because the
 * failure is structural (a missing call site) rather than behavioural. It
 * asserts both halves of the wiring: mounted app-wide, and torn down with the
 * layout's other reconnect registrations.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '..')
const layout = readFileSync(resolve(src, 'layouts/DefaultLayout.vue'), 'utf8')

describe('useActiveProductReconciliation mount site (FE-9412)', () => {
  it('is mounted app-wide in DefaultLayout', () => {
    expect(/useActiveProductReconciliation\(\)/.test(layout)).toBe(true)
  })

  it('hands its teardown to the layout, which unregisters on unmount', () => {
    expect(/resyncUnregisters\.push\(useActiveProductReconciliation\(\)\.stop\)/.test(layout)).toBe(
      true,
    )
  })
})
