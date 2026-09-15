import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { describe, it, expect, vi, afterEach } from 'vitest'

vi.mock('@/services/api', async (importOriginal) => await importOriginal())

import { api, apiClient } from '@/services/api'

describe('FE-9604 api.assignments hits the /api/v1/products router', () => {
  afterEach(() => vi.restoreAllMocks())

  it('list(productId) GETs /api/v1/products/<id>/agent-assignments', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { assignments: [] } })
    await api.assignments.list('prod-1')
    expect(get).toHaveBeenCalledTimes(1)
    expect(get.mock.calls[0][0]).toBe('/api/v1/products/prod-1/agent-assignments')
  })

  it('toggle(productId, templateId, true) PUTs /api/v1/products/<id>/agent-assignments/<tid> with {is_active:true}', async () => {
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })
    await api.assignments.toggle('prod-1', 'tpl-9', true)
    expect(put).toHaveBeenCalledTimes(1)
    expect(put.mock.calls[0][0]).toBe('/api/v1/products/prod-1/agent-assignments/tpl-9')
    expect(put.mock.calls[0][1]).toEqual({ is_active: true })
  })

  it('guard: api.js never uses the un-versioned /api/products/ prefix', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const source = readFileSync(resolve(here, '../api.js'), 'utf8')
    const offenders = source
      .split('\n')
      .map((line, i) => ({ line, n: i + 1 }))
      .filter(({ line }) => /['"`]\/api\/products\//.test(line))
    expect(offenders, `un-versioned product paths: ${JSON.stringify(offenders)}`).toEqual([])
  })
})
