/**
 * chainRunRedirect.spec.js — FE-9655d
 *
 * A chain is shown as one group on the Jobs board, so the old chain links
 * (/projects/<member>?run=<id>) keep working by landing on the board with that
 * chain's group highlighted. A plain project link is untouched.
 *
 * Asserted at the route-table layer, where the redirect lives.
 *
 * Edition scope: Both.
 */
import { describe, it, expect } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import { routes } from '@/router'

function isolatedRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

describe('?run= chain links land on the Jobs board (FE-9655d)', () => {
  it('redirects /projects/<id>?run=<run> to the board with the run carried over', async () => {
    const router = isolatedRouter()
    await router.push('/projects/p1?run=run-9&tab=jobs')
    const current = router.currentRoute.value
    expect(current.name).toBe('JobsViewport')
    expect(current.query).toEqual({ run: 'run-9' })
  })

  // FE-9681: the project page is retired; a plain project link lands on the
  // board too, with the project named (see projectLaunchRedirect.fe9681.spec).
  it('a plain project link lands on the board with the project named', async () => {
    const router = isolatedRouter()
    await router.push('/projects/p1?via=jobs')
    expect(router.currentRoute.value.name).toBe('JobsViewport')
    expect(router.currentRoute.value.query).toEqual({ project: 'p1' })
  })
})
