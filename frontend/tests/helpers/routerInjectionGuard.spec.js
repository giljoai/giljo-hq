/**
 * routerInjectionGuard.spec.js — FE-9427
 *
 * Proves the guard has teeth, end to end and in isolation, WITHOUT leaving a
 * violation in the tree for it to find. Two halves:
 *
 *   1. End-to-end, through the real warnHandler tests/setup.js installs: mount a
 *      component that calls useRouter()/useRoute() with no router and drain the
 *      SAME singleton instance the global afterEach uses. Draining here is what
 *      keeps the deliberate violation from failing this file — the guard is
 *      being exercised, not evaded.
 *   2. In isolation, on a fresh instance, against the exact warning strings Vue
 *      emits — including the ones it must NOT claim, which is the half that
 *      proves the scope is real rather than asserted.
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  createRouterInjectionGuard,
  routerInjectionGuard,
} from './routerInjectionGuard.js'

const NeedsRouter = defineComponent({
  name: 'NeedsRouter',
  setup() {
    useRouter()
    return () => null
  },
})

const NeedsRoute = defineComponent({
  name: 'NeedsRoute',
  setup() {
    useRoute()
    return () => null
  },
})

describe('routerInjectionGuard — end to end through the installed warnHandler', () => {
  it('catches a component mounted without a router and names the fix', () => {
    mount(NeedsRouter).unmount()

    const message = routerInjectionGuard.drainMessage()

    expect(message).not.toBeNull()
    expect(message).toContain('Symbol(router)')
    expect(message).toContain('createMemoryHistory')
    // The advice has to survive: this is the line a future author acts on.
    expect(message).toContain('not a catch-all')
  })

  it('catches useRoute() as well as useRouter()', () => {
    mount(NeedsRoute).unmount()

    const message = routerInjectionGuard.drainMessage()

    expect(message).not.toBeNull()
    expect(message).toContain('Symbol(route location)')
  })

  it('reports both keys once when a mount is missing both', () => {
    mount(NeedsRouter).unmount()
    mount(NeedsRoute).unmount()
    mount(NeedsRouter).unmount()

    const message = routerInjectionGuard.drainMessage()

    expect(message).toContain('Symbol(route location) or Symbol(router)')
  })

  it('drains, so one offending test cannot fail the next one', () => {
    mount(NeedsRouter).unmount()

    expect(routerInjectionGuard.drainMessage()).not.toBeNull()
    expect(routerInjectionGuard.drainMessage()).toBeNull()
  })
})

describe('routerInjectionGuard — scope', () => {
  it('claims exactly the two router keys', () => {
    const guard = createRouterInjectionGuard()

    expect(guard.record('injection "Symbol(router)" not found.')).toBe(true)
    expect(guard.record('injection "Symbol(route location)" not found.')).toBe(true)
    expect(() => guard.assertNone()).toThrow(/FE-9427/)
  })

  it('does NOT claim other injections — mounting a child without its provider stays legal', () => {
    const guard = createRouterInjectionGuard()

    // Real strings from this suite's own warning population. If the guard ever
    // starts claiming these it has become the blanket policy FE-9403 rejected.
    expect(guard.record('injection "Symbol(pinia)" not found.')).toBe(false)
    expect(guard.record('injection "Symbol(vuetify:defaults)" not found.')).toBe(false)
    expect(guard.record('injection "commHubStore" not found.')).toBe(false)

    expect(() => guard.assertNone()).not.toThrow()
  })

  it('does NOT claim unrelated warnings that merely mention the router', () => {
    const guard = createRouterInjectionGuard()

    expect(guard.record('Failed to resolve component: router-link')).toBe(false)
    expect(guard.record('Invalid prop: type check failed for prop "router".')).toBe(false)

    expect(() => guard.assertNone()).not.toThrow()
  })

  it('stays silent when nothing was recorded', () => {
    const guard = createRouterInjectionGuard()

    expect(guard.drainMessage()).toBeNull()
    expect(() => guard.assertNone()).not.toThrow()
  })
})
