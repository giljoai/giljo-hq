/**
 * The Database settings tab reads host, port, name and user. Only
 * GET /api/v1/config/database returns them; /api/v1/settings/database returns
 * the tenant's settings dict, which has none of those keys.
 */
import { describe, it, expect, vi } from 'vitest'

vi.unmock('@/services/api')

describe('api.settings.getDatabase contract', () => {
  it('reads the endpoint that carries the database connection values', async () => {
    const { api, apiClient } = await import('@/services/api')
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: {} })

    await api.settings.getDatabase()

    expect(getSpy).toHaveBeenCalledWith('/api/v1/config/database')
    getSpy.mockRestore()
  })
})
