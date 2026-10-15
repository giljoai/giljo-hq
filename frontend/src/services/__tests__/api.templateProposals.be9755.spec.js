import { describe, it, expect, vi, afterEach } from 'vitest'

vi.mock('@/services/api', async (importOriginal) => await importOriginal())

import { api, apiClient } from '@/services/api'

describe('BE-9755 api.templateProposals', () => {
  afterEach(() => vi.restoreAllMocks())

  it('list() GETs the collection with no trailing slash', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { count: 0, proposals: [] } })
    await api.templateProposals.list()
    expect(get.mock.calls[0][0]).toBe('/api/v1/template-proposals')
  })

  it('count() GETs /count', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { count: 2 } })
    await api.templateProposals.count()
    expect(get.mock.calls[0][0]).toBe('/api/v1/template-proposals/count')
  })

  it('apply(id) POSTs /{id}/apply with no body', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { applied: true } })
    await api.templateProposals.apply('p-1')
    expect(post.mock.calls[0][0]).toBe('/api/v1/template-proposals/p-1/apply')
    expect(post.mock.calls[0][1]).toBeUndefined()
  })

  it('reject(id) POSTs /{id}/reject with no body', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { rejected: true } })
    await api.templateProposals.reject('p-1')
    expect(post.mock.calls[0][0]).toBe('/api/v1/template-proposals/p-1/reject')
    expect(post.mock.calls[0][1]).toBeUndefined()
  })
})
