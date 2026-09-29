/**
 * projectLaunchRedirect.fe9681.spec.js — FE-9681
 *
 * The project page is retired: /projects/<id> lands on the Jobs board with
 * that project as the arrival, and the page's one-shot flags ride along
 * (review=1, decide=1; tab=jobs becomes detail=1). Old chain links keep the
 * FE-9655d behaviour. The route NAME stays as a redirect so a stale
 * bookmark or an older push still resolves.
 *
 * Edition scope: Both.
 */
import { describe, it, expect } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import { routes } from '@/router'

function isolatedRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

describe('/projects/<id> lands on the Jobs board (FE-9681)', () => {
  it('a plain project link arrives at the board with the project named', async () => {
    const router = isolatedRouter()
    await router.push('/projects/p1')
    expect(router.currentRoute.value.name).toBe('JobsViewport')
    expect(router.currentRoute.value.query).toEqual({ project: 'p1' })
  })

  it('carries review=1 and decide=1 over, drops via, and turns tab=jobs into detail=1', async () => {
    const router = isolatedRouter()
    await router.push('/projects/p2?via=jobs&review=1')
    expect(router.currentRoute.value.query).toEqual({ project: 'p2', review: '1' })
    await router.push('/projects/p3?tab=jobs&decide=1')
    expect(router.currentRoute.value.query).toEqual({ project: 'p3', decide: '1', detail: '1' })
    await router.push('/projects/p4?tab=launch')
    expect(router.currentRoute.value.query).toEqual({ project: 'p4' })
  })

  it('an old chain link still lands on its group (FE-9655d), not on a card', async () => {
    const router = isolatedRouter()
    await router.push('/projects/p5?run=run-9&tab=jobs')
    expect(router.currentRoute.value.name).toBe('JobsViewport')
    expect(router.currentRoute.value.query).toEqual({ run: 'run-9' })
  })

  it('a named push to the retired route resolves to the board too', async () => {
    const router = isolatedRouter()
    await router.push({ name: 'ProjectLaunch', params: { projectId: 'p6' }, query: { decide: '1' } })
    expect(router.currentRoute.value.name).toBe('JobsViewport')
    expect(router.currentRoute.value.query).toEqual({ project: 'p6', decide: '1' })
  })
})
