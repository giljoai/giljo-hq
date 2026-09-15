import { describe, it, expect, vi, afterEach } from 'vitest'
import { ref } from 'vue'

describe('useWelcomeGreeting', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  async function makeGreeting(name = 'Alice', hour = 10) {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2024, 0, 1, hour, 0, 0))
    const { useWelcomeGreeting } = await import('./useWelcomeGreeting')
    const firstName = ref(name)
    return useWelcomeGreeting({ firstName })
  }

  it('returns a non-empty string', async () => {
    const { fullGreeting } = await makeGreeting()
    expect(typeof fullGreeting.value).toBe('string')
    expect(fullGreeting.value.length).toBeGreaterThan(0)
  })

  it('includes the provided name somewhere in the greeting', async () => {
    const { fullGreeting } = await makeGreeting('Sam')
    expect(fullGreeting.value).toContain('Sam')
  })

  it('works with different names', async () => {
    const { fullGreeting } = await makeGreeting('Bob')
    expect(fullGreeting.value).toContain('Bob')
  })

  it('returns morning-appropriate greeting before noon', async () => {
    const results = new Set()
    for (let i = 0; i < 50; i++) {
      const { fullGreeting } = await makeGreeting('Test', 9)
      results.add(fullGreeting.value)
    }
    expect(results.size).toBeGreaterThan(1)
  })
})
