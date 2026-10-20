/**
 * FE-9794 (ONB-02): a product created from the blank form lost its Brand &
 * Design Guidelines. ProductForm sends brand_guidelines, the backend create
 * route accepts it, but api.products.create built an explicit payload that left
 * it out. tests/setup.js mocks the api wholesale, so this unmocks the real
 * module and asserts the body actually posted.
 */
import { describe, it, expect, vi } from 'vitest'

vi.unmock('@/services/api')

describe('api.products.create (FE-9794 contract)', () => {
  it('posts brand_guidelines with the new product', async () => {
    const { api, apiClient } = await import('@/services/api')
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'p-1' } })

    await api.products.create({ name: 'Blank product', brand_guidelines: 'Teal accents, no gradients' })

    expect(postSpy).toHaveBeenCalledWith(
      '/api/v1/products/',
      expect.objectContaining({ name: 'Blank product', brand_guidelines: 'Teal accents, no gradients' }),
    )

    postSpy.mockRestore()
  })

  it('sends null when no guidelines were entered, matching the other optional text fields', async () => {
    const { api, apiClient } = await import('@/services/api')
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'p-2' } })

    await api.products.create({ name: 'Blank product', brand_guidelines: '' })

    expect(postSpy.mock.calls[0][1]).toHaveProperty('brand_guidelines', null)

    postSpy.mockRestore()
  })
})
