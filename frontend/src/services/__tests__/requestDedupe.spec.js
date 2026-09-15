import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/services/api', async (importOriginal) => await importOriginal())

import { api, apiClient, __resetRequestDedupe } from '@/services/api'

describe('FE-6059 request de-duplication', () => {
  beforeEach(() => {
    __resetRequestDedupe()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    __resetRequestDedupe()
  })

  it('collapses N concurrent api.products.list() calls into ONE network request', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [{ id: 1 }] })

    const results = await Promise.all([
      api.products.list(),
      api.products.list(),
      api.products.list(),
      api.products.list(),
      api.products.list(),
    ])

    expect(get).toHaveBeenCalledTimes(1)
    for (const r of results) expect(r.data).toEqual([{ id: 1 }])
  })

  it('serves products.list() from cache within the short TTL, then refetches after it expires', async () => {
    vi.useFakeTimers()
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })

    await api.products.list()
    await api.products.list()
    expect(get).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(1600)
    await api.products.list()
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('keys de-dupe by params so a filtered list does not collide with the bare list', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })

    await Promise.all([api.products.list(), api.products.list({ q: 'x' })])

    expect(get).toHaveBeenCalledTimes(2)
  })

  it('a rejected request is not cached — the next call retries', async () => {
    const get = vi
      .spyOn(apiClient, 'get')
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ data: [{ id: 2 }] })

    await expect(api.products.list()).rejects.toThrow('boom')
    const ok = await api.products.list()

    expect(get).toHaveBeenCalledTimes(2)
    expect(ok.data).toEqual([{ id: 2 }])
  })

  it('collapses every independent caller of the default-product read into ONE network request per page load', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { has_active_product: false, product: null } })

    const results = await Promise.all([
      api.products.getDefault(),
      api.products.getDefault(),
      api.products.getDefault(),
      api.products.getDefault(),
    ])

    expect(get).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenCalledWith('/api/v1/products/refresh-active')
    for (const r of results) expect(r.data).toEqual({ has_active_product: false, product: null })
  })

  it('the default-product read is deduped independently of products.list (different keys)', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })

    await Promise.all([api.products.list(), api.products.getDefault()])

    expect(get).toHaveBeenCalledTimes(2)
  })
})
