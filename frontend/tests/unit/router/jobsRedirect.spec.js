/**
 * Regression: every legacy Jobs URL resolves onto the Jobs board.
 *
 * FE-9655e made the board the single Jobs landing, so the two aliases that used
 * to point at the launch pane now point at the board:
 *   - /jobs    (the bare bookmark that once fell to the NotFound catch-all)
 *   - /launch  (the pane that resolved an active project for the nav; retired)
 * And the chain deep link FE-9655d already re-targeted stays verified here:
 *   - /projects/<id>?run=<id> → the board with that chain group highlighted.
 *
 * Asserted at the route-table layer (the layer the aliases live in), so a future
 * route-table edit that drops or mistargets one fails here.
 */

import { describe, it, expect } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import { routes } from '@/router'

const BOARD = '/jobs-overview'

describe('Jobs landing redirects (FE-9655e)', () => {
  it('declares a /jobs route that redirects to the board', () => {
    const jobs = routes.find((r) => r.path === '/jobs')
    expect(jobs).toBeDefined()
    expect(jobs.redirect).toBe(BOARD)
  })

  it('declares a /launch route that redirects to the board', () => {
    const launch = routes.find((r) => r.path === '/launch')
    expect(launch).toBeDefined()
    expect(launch.redirect).toBe(BOARD)
    // The pane is gone, so the alias must not still mount a component.
    expect(launch.component).toBeUndefined()
  })

  it('navigating to /jobs lands on the board (not NotFound)', async () => {
    // Build an isolated router from the real route table — no auth guard, no API.
    // String redirects are followed during navigation, not in resolve(), so push.
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/jobs')
    const current = router.currentRoute.value
    expect(current.name).toBe('JobsViewport')
    expect(current.path).toBe(BOARD)
    expect(current.matched.some((r) => r.name === 'NotFound')).toBe(false)
  })

  it('navigating to /launch lands on the board', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/launch')
    const current = router.currentRoute.value
    expect(current.name).toBe('JobsViewport')
    expect(current.path).toBe(BOARD)
  })

  it('an old /launch?via=jobs link lands on the board too', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/launch?via=jobs')
    expect(router.currentRoute.value.name).toBe('JobsViewport')
  })

  it('an old chain link opens the board with that group highlighted (FE-9655d, verified not duplicated)', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/projects/member-2?run=run-7')
    const current = router.currentRoute.value
    expect(current.name).toBe('JobsViewport')
    expect(current.query.run).toBe('run-7')
  })

  // FE-9681: the project page is retired; a plain project link lands on the
  // board with the project named.
  it('a plain project link lands on the board with the project named', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/projects/solo-1?via=jobs')
    expect(router.currentRoute.value.name).toBe('JobsViewport')
    expect(router.currentRoute.value.query).toEqual({ project: 'solo-1' })
  })

  it('still routes an unknown URL to NotFound (catch-all intact)', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/this-route-does-not-exist')
    expect(router.currentRoute.value.name).toBe('NotFound')
  })
})
