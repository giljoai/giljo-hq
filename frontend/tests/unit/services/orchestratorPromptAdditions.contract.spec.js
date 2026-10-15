/**
 * BE-9754: the orchestrator prompt editor saves the user's ADDITIONS, which the
 * server layers on top of the built-in prompt. The component spec mocks
 * `@/services/api` wholesale, so the request body is pinned here against the
 * real module: PUT carries `additions` (+ product_id), never the full `content`
 * (a `content` PUT is the legacy full-replacement path).
 */
import { describe, it, expect, vi } from 'vitest'

vi.unmock('@/services/api')

describe('api.system.updateOrchestratorPrompt (BE-9754 contract)', () => {
  it('PUTs { additions, product_id } and no content field', async () => {
    const { api, apiClient } = await import('@/services/api')
    const putSpy = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })

    await api.system.updateOrchestratorPrompt('Extra rule.', 'product-1')

    expect(putSpy).toHaveBeenCalledWith('/api/v1/system/orchestrator-prompt', {
      additions: 'Extra rule.',
      product_id: 'product-1',
    })
    expect(putSpy.mock.calls[0][1]).not.toHaveProperty('content')

    putSpy.mockRestore()
  })

  it('refuses to PUT without a product id', async () => {
    const { api, apiClient } = await import('@/services/api')
    const putSpy = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })

    expect(() => api.system.updateOrchestratorPrompt('Extra rule.')).toThrow(/product id/)
    expect(() => api.system.updateOrchestratorPrompt('Extra rule.', null)).toThrow(/product id/)
    expect(putSpy).not.toHaveBeenCalled()

    putSpy.mockRestore()
  })

  it('reads and resets with product_id; a reset without one is refused, a read stays open', async () => {
    const { api, apiClient } = await import('@/services/api')
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: {} })
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })

    await api.system.getOrchestratorPrompt('product-1')
    expect(getSpy).toHaveBeenCalledWith('/api/v1/system/orchestrator-prompt', {
      params: { product_id: 'product-1' },
    })
    await api.system.resetOrchestratorPrompt('product-1')
    expect(postSpy).toHaveBeenCalledWith('/api/v1/system/orchestrator-prompt/reset', null, {
      params: { product_id: 'product-1' },
    })

    expect(() => api.system.resetOrchestratorPrompt(null)).toThrow(/product id/)
    expect(postSpy).toHaveBeenCalledTimes(1)
    // the read-only preview in AgentDetailsModal still reads without a product
    await api.system.getOrchestratorPrompt()
    expect(getSpy).toHaveBeenCalledTimes(2)

    getSpy.mockRestore()
    postSpy.mockRestore()
  })
})
