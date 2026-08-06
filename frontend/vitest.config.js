import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import os from 'node:os'

const cpus = os.availableParallelism?.() ?? os.cpus().length

// FE-9341: vitest sizes its fork pool as `availableParallelism() - 1`, taken
// from the total core count with no awareness of what else is running — 23
// forks on the 24-core CI box (which runs up to three jobs at once), 47 on a
// 48-core workstation. Every fork requests module transforms from the single
// main process, so the queue in front of that pipeline grows with the worker
// count, and the wait lands inside whichever test triggered the lazy import.
// Bounding the pool cut transform time by close to an order of magnitude on
// the CI runner, comparing the same workflow before and after. No absolute
// transform figure is quoted here on purpose: that cost is not comparable
// across machines or cache states, only within one box measured back to back.
//
// The divisor is the term that protects a shared box. The cap only binds at 36
// cores or more, so it never applies on CI and exists to stop a very large
// machine from re-creating the congestion. Below 8 cores the floor of 2 wins,
// and there it yields *more* workers than vitest's own default of `cpus - 1`
// rather than fewer — deliberate, since a 1-2 core box has no co-tenants to
// leave room for and the budget below covers the slower run.
export function resolveMaxWorkers(coreCount) {
  return Math.max(2, Math.min(12, Math.floor(coreCount / 4)))
}

const maxWorkers = resolveMaxWorkers(cpus)

export default defineConfig({
  plugins: [vue()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.js'],
    maxWorkers,
    // FE-9341: vitest charges the cost of transforming a lazily-imported
    // component graph to whichever test triggered it, and under a large worker
    // pool that queued cost can exceed the default budget — so those specs
    // fail on runner infrastructure rather than on anything they assert. How
    // large the cost is varies by machine and cache state, so no figure is
    // asserted here. This is not FE-9338's widened guess: those tests already
    // await their real signals, and the transform is work they cannot await or
    // avoid. 15s still fails a genuinely hung test. If a timeout resurfaces,
    // the next lever is a lower divisor above, not a bigger budget here.
    testTimeout: 15000,
    // De-flake 2026-05-28: vitest pipes intercepted console output to the main
    // process over the worker RPC channel. Under parallel workers a console
    // log emitted as a worker is tearing down races the RPC close, surfacing as
    // "EnvironmentTeardownError: Closing rpc while onUserConsoleLog was pending"
    // and failing the whole run non-deterministically even when every test
    // passes. Disabling interception removes that RPC path (logs print
    // directly to stdout instead). Does not affect vi.spyOn(console) assertions.
    disableConsoleIntercept: true,
    include: ['tests/**/*.spec.js', 'tests/**/*.spec.ts', 'tests/**/*.spec.vue', 'src/**/*.spec.js', 'src/**/*.spec.ts', 'src/**/*.spec.vue'],
    exclude: ['tests/e2e/**', '**/node_modules/**'],
    server: {
      deps: {
        inline: ['vuetify']
      }
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: [
        'src/components/**',
        'src/services/**',
        'src/stores/**'
      ],
      exclude: [
        '**/node_modules/**',
        '**/dist/**',
        '**/*.d.ts',
        '**/__tests__/**',
        '**/index.js'
      ],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 75,
        statements: 80
      }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '/icons': path.resolve(__dirname, './public/icons'),
    }
  }
})
