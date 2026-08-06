/**
 * FE-9341 — the suite must not size its worker pool to the whole machine.
 *
 * Edition Scope: CE (test infrastructure).
 *
 * Vitest's default `maxWorkers` is `availableParallelism() - 1`, a number taken
 * from the total core count with no awareness of what else is running. On the
 * 24-core CI box that is 23 forks competing with up to two other concurrent CI
 * jobs; on a 48-core workstation it is 47. Every fork requests module
 * transforms from the single main process, so the queue in front of that
 * pipeline grows with the worker count — and the wait is charged to whichever
 * individual test triggered the lazy import, so trivial mount-and-assert tests
 * fail on their own budget. Bounding the pool cut transform time by close to
 * an order of magnitude on the CI runner. Absolute transform figures are not
 * quoted here or in the config: they are not comparable across machines or
 * cache states, only within one box measured back to back.
 *
 * These assertions are the guard, not the fix. They exist so a future edit
 * cannot quietly hand the pool back to the machine size.
 */
import { describe, it, expect } from 'vitest'
import os from 'node:os'
import config, { resolveMaxWorkers } from '../../../vitest.config.js'

const cpus = os.availableParallelism?.() ?? os.cpus().length

describe('vitest.config.js — worker pool is bounded (FE-9341)', () => {
  it('pins maxWorkers explicitly instead of inheriting the machine-sized default', () => {
    expect(config.test.maxWorkers).toBeDefined()
    expect(typeof config.test.maxWorkers).toBe('number')
  })

  // Asserting one resolved value only tests the formula at whatever core count
  // this box happens to have, and it is weakest on the 24-core CI box: there
  // the cap term is not even reached, so a cap edit resolves identically and
  // slips through. Walk the formula instead, so every term has a core count
  // that pins it — the floor below 8 cores, the divisor at 24, the cap at 96.
  it.each([
    [1, 2],
    [2, 2],
    [4, 2],
    [8, 2],
    [24, 6],
    [48, 12],
    [96, 12],
  ])('resolves %i cores to %i workers', (coreCount, expected) => {
    expect(resolveMaxWorkers(coreCount)).toBe(expected)
  })

  it('applies that same formula to the machine actually running the suite', () => {
    expect(config.test.maxWorkers).toBe(resolveMaxWorkers(cpus))
  })

  it('budgets enough time for a transform charged to a test body, without going open-ended', () => {
    // Vitest charges runner-side module transform to whichever test triggered
    // the lazy import, and a large worker pool can queue that past the 5000ms
    // default. The upper bound keeps this a bounded allowance rather than a
    // number a future edit can widen indefinitely — if a timeout resurfaces,
    // the lever is a lower divisor above, not a bigger budget here.
    expect(config.test.testTimeout).toBeGreaterThanOrEqual(15000)
    expect(config.test.testTimeout).toBeLessThanOrEqual(20000)
  })
})
