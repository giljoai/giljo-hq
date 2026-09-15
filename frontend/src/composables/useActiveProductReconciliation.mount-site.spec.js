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
