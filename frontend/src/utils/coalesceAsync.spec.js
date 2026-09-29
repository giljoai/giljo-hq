import { describe, it, expect } from 'vitest'
import { coalesceAsync } from './coalesceAsync'

function deferred() {
  let resolve
  const promise = new Promise((r) => (resolve = r))
  return { promise, resolve }
}

describe('coalesceAsync (FE-9689)', () => {
  it('never runs two at once, and folds calls made meanwhile into one more run', async () => {
    const gates = []
    let running = 0
    let maxRunning = 0
    const seen = []
    let scope = 'all'
    const run = coalesceAsync(async () => {
      running++
      maxRunning = Math.max(maxRunning, running)
      seen.push(scope)
      const gate = deferred()
      gates.push(gate)
      await gate.promise
      running--
    })

    const first = run()
    scope = 'product-b'
    const second = run()
    const third = run()
    gates[0].resolve()
    await Promise.resolve()
    await new Promise((r) => setTimeout(r, 0))
    gates[1].resolve()
    await Promise.all([first, second, third])

    expect(maxRunning).toBe(1)
    expect(seen).toEqual(['all', 'product-b'])
  })

  it('runs again for a call made after the previous run finished', async () => {
    let n = 0
    const run = coalesceAsync(async () => {
      n++
    })
    await run()
    await run()
    expect(n).toBe(2)
  })

  it('a failing run does not wedge later calls', async () => {
    let n = 0
    const run = coalesceAsync(async () => {
      n++
      if (n === 1) throw new Error('boom')
    })
    await expect(run()).rejects.toThrow('boom')
    await run()
    expect(n).toBe(2)
  })
})
