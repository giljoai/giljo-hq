/**
 * FE-9397 — the frontend test tier must fail when a control does not render.
 *
 * Regression test at the layer the defect lived: component resolution in the
 * vitest setup, not any one product spec. Before this, a Vuetify tag missing
 * from `config.global.stubs` in tests/setup.js rendered as an inert unknown
 * element and Vue's "Failed to resolve component" warning was written to the
 * console and ignored, so a suite could stay green with a control absent from
 * the test DOM.
 *
 * The end-to-end case below drains the SHARED guard instance that tests/setup.js
 * installs — the same object the global `afterEach` calls — so the guard is
 * proven against a real Vue render rather than against a hand-fed string, while
 * still leaving the run green.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import {
  createUnresolvedAssetGuard,
  unresolvedAssetGuard,
} from './helpers/unresolvedAssetGuard.js'

describe('FE-9397 unresolved component guard', () => {
  describe('against a real Vue render (end to end)', () => {
    it('records a component that does not resolve, so the afterEach can fail the test', () => {
      const wrapper = mount({
        template: '<div><fe9397-deliberately-unresolvable>inner</fe9397-deliberately-unresolvable></div>',
      })

      // Drain the shared instance: this is what tests/setup.js's afterEach
      // would have thrown on. Draining here proves it was armed AND keeps this
      // spec green.
      const recorded = unresolvedAssetGuard.drain()

      expect(recorded).toEqual(['fe9397-deliberately-unresolvable'])

      // The reason the old setup stayed green: the tag still renders, so the
      // DOM looks populated. Pin that, because it is the whole trap — a spec
      // asserting on this element or its slot text passes while the real
      // component is absent.
      expect(wrapper.html()).toContain('fe9397-deliberately-unresolvable')
      expect(wrapper.text()).toBe('inner')
    })

    it('stays silent for a component that IS registered in the stub map', () => {
      const wrapper = mount({
        template: '<v-btn-toggle><v-btn>Alpha</v-btn></v-btn-toggle>',
      })

      expect(unresolvedAssetGuard.drain()).toEqual([])
      expect(wrapper.find('.v-btn-toggle').exists()).toBe(true)
    })
  })

  describe('the guard itself', () => {
    it('throws on drain-and-assert, naming every unresolved component', () => {
      const guard = createUnresolvedAssetGuard()

      guard.warnHandler('Failed to resolve component: v-nope\nIf this is a native custom element...')
      guard.warnHandler('Failed to resolve component: v-also-nope')

      expect(() => guard.assertNone()).toThrow(/v-also-nope, v-nope/)
    })

    it('points the next author at the fix instead of just complaining', () => {
      const guard = createUnresolvedAssetGuard()
      guard.warnHandler('Failed to resolve component: v-nope')

      expect(() => guard.assertNone()).toThrow(/config\.global\.stubs/)
    })

    it('does not fire twice for one failure — assertNone drains what it reports', () => {
      const guard = createUnresolvedAssetGuard()
      guard.warnHandler('Failed to resolve component: v-nope')

      expect(() => guard.assertNone()).toThrow()
      expect(() => guard.assertNone()).not.toThrow()
    })

    it('passes every other Vue warning through untouched', () => {
      const guard = createUnresolvedAssetGuard()
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

      try {
        guard.warnHandler('Invalid prop: type check failed for prop "size"', null, ' at <VBtn>')
        expect(warn).toHaveBeenCalledWith(
          expect.stringContaining('Invalid prop: type check failed for prop "size"'),
        )
      } finally {
        warn.mockRestore()
      }

      expect(() => guard.assertNone()).not.toThrow()
    })

    it('now enforces directives too, and says which kind failed', () => {
      // REVERSAL OF AN FE-9397 ASSERTION, ON PURPOSE (FE-9403).
      //
      // This test used to assert the opposite -- that a directive failure was
      // deliberately NOT enforced -- pinning the boundary so that widening it
      // later would be a decision rather than an accident. FE-9403 is that
      // decision: it ran the experiment FE-9397 was waiting on (register the
      // real `v-draggable` suite-wide with no guard and see what turns red;
      // nothing did, across 396 files, while the directive mounted and ran
      // 1314 times), and widened the guard to the whole resolution class.
      //
      // The report still distinguishes the two kinds, because the fix differs:
      // a component is registered in the stub map, a directive in
      // config.global.directives.
      const guard = createUnresolvedAssetGuard()
      guard.warnHandler('Failed to resolve directive: draggable')

      expect(() => guard.assertNone()).toThrow(/directive/)
      expect(() => {
        const g = createUnresolvedAssetGuard()
        g.warnHandler('Failed to resolve directive: draggable')
        g.assertNone()
      }).toThrow(/draggable/)
    })
  })
})
