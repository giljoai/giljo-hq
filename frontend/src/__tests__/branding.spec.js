import { describe, expect, it } from 'vitest'
import {
  HOUSE_BRAND,
  PRODUCT_NAME,
  PRODUCT_SHORT,
  MCP_ALIAS,
  DESCRIPTOR,
  TWO_HUB_DISAMBIGUATION,
} from '../branding'

describe('branding constants (BE-9275a)', () => {
  it('have the expected identity values', () => {
    expect(HOUSE_BRAND).toBe('GiljoAI')
    expect(PRODUCT_NAME).toBe('Giljo HQ')
    expect(PRODUCT_SHORT).toBe('Giljo HQ')
    expect(MCP_ALIAS).toBe('giljo_hq')
    expect(DESCRIPTOR).toBe(
      'Giljo HQ — project, task, and agent coordination for the one-person software company',
    )
  })

  it('names giljo_amh in the two-hub disambiguation sentence', () => {
    expect(TWO_HUB_DISAMBIGUATION).toContain('giljo_amh')
    expect(TWO_HUB_DISAMBIGUATION).toContain('Giljo HQ')
  })
})
