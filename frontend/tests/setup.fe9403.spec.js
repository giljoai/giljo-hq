/**
 * FE-9403 — the frontend test tier must fail when a DIRECTIVE does not resolve.
 *
 * Regression test at the layer the defect lived: asset resolution in the vitest
 * setup, not any one product spec — the same layer FE-9397 closed for
 * components, now closed for the other half of the class.
 *
 * WHY THIS IS A SEPARATE PROBLEM FROM FE-9397
 *
 * FE-9397 measured that an unresolved *component* degrades to an inert unknown
 * element: the tag, its class and its default-slot children still render, so a
 * text assertion was never lied to. None of that mitigation transfers to a
 * directive. An unresolved directive simply never runs — no partial
 * degradation, no residual DOM, nothing for an assertion to accidentally catch.
 * Everything it was responsible for is absent and Vue says so only in a
 * console.warn.
 *
 * FE-9397 deliberately left directives out of the guard and pinned that
 * exclusion with a spec. This project ran the experiment that decision was
 * waiting on — register the real `v-draggable` across the whole suite with no
 * guard installed, and see what turns red. The answer was nothing: 396 files
 * and 4576 tests stayed green while the directive mounted and ran to completion
 * 1314 times. So no assertion in this suite was being lied to. The guard below
 * exists to keep it that way, because "measured clean once" is not a property
 * that survives on its own.
 *
 * The trap FE-9397 documented is inherited here unchanged: Vue runs
 * `app.config.warnHandler` through `callWithErrorHandling`, so a throw inside
 * the handler is swallowed and the guard silently does not work. The handler
 * records; the global `afterEach` throws.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import {
  createUnresolvedAssetGuard,
  unresolvedAssetGuard,
} from './helpers/unresolvedAssetGuard.js'

describe('FE-9403 unresolved directive guard', () => {
  describe('against a real Vue render (end to end)', () => {
    it('records a directive that does not resolve, so the afterEach can fail the test', () => {
      const wrapper = mount({
        template: '<div v-fe9403-deliberately-unresolvable>inner</div>',
      })

      // Drain the shared instance — the same object tests/setup.js's afterEach
      // throws on. Draining here proves it was armed AND keeps this spec green.
      expect(unresolvedAssetGuard.drain()).toEqual(['fe9403-deliberately-unresolvable'])

      // The reason this stayed green before FE-9403, and the half that differs
      // from an unresolved component: the element renders perfectly normally.
      // Nothing in the DOM records that the directive was ever asked for, so
      // there is no residue an assertion could trip over.
      expect(wrapper.html()).toBe('<div>inner</div>')
    })

    it('resolves v-draggable and actually runs it, rather than merely not warning', () => {
      // Mirrors BaseDialog.vue:10 — `<v-card v-draggable>` with a `.dlg-header`
      // inside. That handle is the component's own markup, so it survives the
      // flat stub map, which is why the directive reaches its real work here.
      const wrapper = mount({
        template:
          '<div class="v-dialog"><div v-draggable class="card"><div class="dlg-header">Title</div></div></div>',
      })

      expect(unresolvedAssetGuard.drain()).toEqual([])

      // Not "it did not warn" — proof the directive body executed. A
      // registration that resolved to something inert would pass a
      // warning-only assertion and fail this one.
      const handle = wrapper.find('.dlg-header').element
      expect(handle.style.cursor).toBe('move')
      expect(handle.style.userSelect).toBe('none')
      expect(wrapper.find('.card').element._draggableCleanup).toBeTypeOf('function')
    })
  })

  describe('the guard itself', () => {
    it('throws on drain-and-assert for a directive, naming it', () => {
      const guard = createUnresolvedAssetGuard()

      guard.warnHandler('Failed to resolve directive: draggable')

      expect(() => guard.assertNone()).toThrow(/draggable/)
    })

    it('reports components and directives together when both fail in one test', () => {
      const guard = createUnresolvedAssetGuard()

      guard.warnHandler('Failed to resolve component: v-nope')
      guard.warnHandler('Failed to resolve directive: draggable')

      expect(() => guard.assertNone()).toThrow(/draggable/)
      expect(() => {
        const g = createUnresolvedAssetGuard()
        g.warnHandler('Failed to resolve component: v-nope')
        g.warnHandler('Failed to resolve directive: draggable')
        g.assertNone()
      }).toThrow(/v-nope/)
    })

    it('tells a directive failure apart from a component one in what it says to fix', () => {
      // The two halves need different advice: a component is registered in the
      // stub map, a directive in config.global.directives. A guard that gave
      // stub-map advice for a directive miss would send the next author to the
      // wrong file.
      const guard = createUnresolvedAssetGuard()
      guard.warnHandler('Failed to resolve directive: draggable')

      expect(() => guard.assertNone()).toThrow(/config\.global\.directives/)
    })

    it('still passes every other Vue warning through untouched', () => {
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
  })
})
